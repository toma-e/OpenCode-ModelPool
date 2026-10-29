"""Module de simulation budgétaire et d'analyse des quotas pour les agents.

Ce module permet de :
1. Calculer les coûts prévisionnels mensuels par agent et pour l'ensemble du parc.
2. Analyser les économies générées par les modèles gratuits.
3. Détecter les risques de dépassement de quotas (rate limits) pour les modèles free_tier.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Sequence

from src.selector import AgentRequirement, Model, SelectionResult

# Seuil de volume mensuel au-delà duquel un modèle free_tier risque d'atteindre
# des rate limits agressives (ex: 50 requêtes/jour ou ~500k tokens/mois)
FREE_TIER_MONTHLY_TOKEN_THRESHOLD = 1_000_000


@dataclass(frozen=True)
class AgentBudgetReport:
    """Rapport budgétaire détaillé pour un agent individuel."""

    agent_name: str
    model_id: str
    tier: str
    estimated_input_tokens: int
    estimated_output_tokens: int
    monthly_input_cost: float
    monthly_output_cost: float
    monthly_total_cost: float
    max_budget: Optional[float] = None
    budget_exceeded: bool = False
    quota_warning: Optional[str] = None
    channel_provider: str = ""
    pricing_source: str = ""
    is_local: bool = False
    is_estimable: bool = True
    disclaimer: str = "Prévision estimative non contractuelle (hors coûts d'infrastructure/matériel local)."


@dataclass(frozen=True)
class FleetBudgetReport:
    """Rapport budgétaire global consolidé pour l'ensemble des agents."""

    total_monthly_cost: float
    total_tokens: int
    free_tier_savings: float
    agent_reports: List[AgentBudgetReport]

    @property
    def has_budget_warnings(self) -> bool:
        """Indique si un agent dépasse son budget ou présente un risque de quota."""
        return any(r.budget_exceeded or r.quota_warning for r in self.agent_reports)

    @property
    def is_total_estimable(self) -> bool:
        """Indique si le coût de tous les agents assignés est estimable."""
        return all(r.is_estimable for r in self.agent_reports if r.model_id != "aucun")


def calculate_agent_cost(
    model: Model,
    input_tokens: int,
    output_tokens: int,
) -> tuple[float, float, float]:
    """Calcule les coûts d'entrée, de sortie et total pour un volume de tokens donné."""
    return model.calculate_cost(input_tokens, output_tokens)


def simulate_agent_budget(
    agent_req: AgentRequirement,
    model: Optional[Model],
    execution_target: Optional[Any] = None,
) -> AgentBudgetReport:
    """Calcule le budget prévisionnel d'un agent avec son modèle attribué et son canal d'exécution."""
    input_tokens = agent_req.estimated_tokens_input
    output_tokens = agent_req.estimated_tokens_output
    total_tokens = input_tokens + output_tokens

    if not model:
        return AgentBudgetReport(
            agent_name=agent_req.name,
            model_id="aucun",
            tier="non_attribué",
            estimated_input_tokens=input_tokens,
            estimated_output_tokens=output_tokens,
            monthly_input_cost=0.0,
            monthly_output_cost=0.0,
            monthly_total_cost=0.0,
            max_budget=agent_req.max_monthly_budget,
            budget_exceeded=False,
            quota_warning="Aucun modèle attribué pour exécuter les tâches.",
            disclaimer="Aucun modèle configuré.",
        )

    channel_provider = getattr(execution_target, "channel_provider", "") if execution_target else ""
    pricing_source = getattr(execution_target, "pricing_source", "catalog") if execution_target else "catalog"
    is_local = getattr(execution_target, "is_local", False) if execution_target else False

    if execution_target is not None:
        cost_in = (input_tokens / 1_000_000) * execution_target.effective_cost_input_per_m
        cost_out = (output_tokens / 1_000_000) * execution_target.effective_cost_output_per_m
        total_cost = cost_in + cost_out
    else:
        cost_in, cost_out, total_cost = calculate_agent_cost(model, input_tokens, output_tokens)

    # Disclaimers explicites (MP-210)
    if is_local:
        disclaimer = "Exécution locale (0$ API, hors infrastructure et consommation matérielle)."
    else:
        disclaimer = "Prévision estimative non contractuelle (tarifs API hors taxes)."

    # Vérification du plafond budgétaire
    budget_exceeded = False
    if agent_req.max_monthly_budget is not None and total_cost > agent_req.max_monthly_budget:
        budget_exceeded = True

    # Analyse des quotas free_tier (MP-211 : avertissement indicatif)
    quota_warning: Optional[str] = None
    if (model.is_free or total_cost == 0.0) and total_tokens > FREE_TIER_MONTHLY_TOKEN_THRESHOLD:
        quota_warning = (
            f"Risque d'atteinte des limites : volume estimé ({total_tokens:,} tokens/mois) élevé pour un palier gratuit. "
            f"Attention aux limites de débit (RPM/TPM). Quotas précis non garantis par l'API."
        )

    # Éligibilité de l'estimation de coût (MP-210)
    is_estimable = True
    if pricing_source == "unknown":
        is_estimable = False
    elif not is_local and not model.is_free:
        if cost_in == 0.0 and cost_out == 0.0 and model.tier == "pay_as_you_go":
            is_estimable = False

    return AgentBudgetReport(
        agent_name=agent_req.name,
        model_id=model.id,
        tier=model.tier,
        estimated_input_tokens=input_tokens,
        estimated_output_tokens=output_tokens,
        monthly_input_cost=cost_in,
        monthly_output_cost=cost_out,
        monthly_total_cost=total_cost,
        max_budget=agent_req.max_monthly_budget,
        budget_exceeded=budget_exceeded,
        quota_warning=quota_warning,
        channel_provider=channel_provider,
        pricing_source=pricing_source,
        is_local=is_local,
        is_estimable=is_estimable,
        disclaimer=disclaimer,
    )


def simulate_fleet_budget(
    results: Sequence[SelectionResult],
    agents: Sequence[AgentRequirement],
    reference_paid_cost_per_m: float = 0.50,
    execution_targets: Optional[Sequence[Optional[Any]]] = None,
) -> FleetBudgetReport:
    """Simule le coût total mensuel de l'ensemble des agents.

    Args:
        results: Résultats d'attribution de chaque agent.
        agents: Profils d'exigence des agents avec estimations de tokens.
        reference_paid_cost_per_m: Coût de référence payant par 1M tokens pour
            estimer les économies réalisées grâce au free_tier.
        execution_targets: Cibles d'exécution optionnelles associées à chaque résultat.

    Returns:
        FleetBudgetReport consolidé.
    """
    results_by_name = {r.agent_name: r for r in results}
    targets_by_name: dict[str, Any] = {}
    if execution_targets is not None:
        for sel_res, target in zip(results, execution_targets):
            if sel_res and target:
                targets_by_name[sel_res.agent_name] = target

    agent_reports: List[AgentBudgetReport] = []

    total_cost = 0.0
    total_tokens = 0
    free_tier_savings = 0.0

    for agent in agents:
        res: Optional[SelectionResult] = results_by_name.get(agent.name)
        model = res.model if res else None
        target = targets_by_name.get(agent.name)

        report = simulate_agent_budget(agent, model, execution_target=target)
        agent_reports.append(report)

        total_cost += report.monthly_total_cost
        agent_tokens = report.estimated_input_tokens + report.estimated_output_tokens
        total_tokens += agent_tokens

        # Estimation des économies si modèle gratuit ou canal local 0$
        if (model and model.is_free) or (target and getattr(target, "is_local", False)):
            savings = (agent_tokens / 1_000_000) * reference_paid_cost_per_m
            free_tier_savings += savings

    return FleetBudgetReport(
        total_monthly_cost=round(total_cost, 4),
        total_tokens=total_tokens,
        free_tier_savings=round(free_tier_savings, 4),
        agent_reports=agent_reports,
    )
