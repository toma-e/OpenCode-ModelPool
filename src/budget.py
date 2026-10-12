"""Module de simulation budgétaire et d'analyse des quotas pour les agents.

Ce module permet de :
1. Calculer les coûts prévisionnels mensuels par agent et pour l'ensemble du parc.
2. Analyser les économies générées par les modèles gratuits.
3. Détecter les risques de dépassement de quotas (rate limits) pour les modèles free_tier.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

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
) -> AgentBudgetReport:
    """Calcule le budget prévisionnel d'un agent avec son modèle attribué."""
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
        )

    cost_in, cost_out, total_cost = calculate_agent_cost(model, input_tokens, output_tokens)

    # Vérification du plafond budgétaire
    budget_exceeded = False
    if agent_req.max_monthly_budget is not None and total_cost > agent_req.max_monthly_budget:
        budget_exceeded = True

    # Analyse des quotas free_tier
    quota_warning: Optional[str] = None
    if model.is_free and total_tokens > FREE_TIER_MONTHLY_TOKEN_THRESHOLD:
        quota_warning = (
            f"Volume estimé ({total_tokens:,} tokens) élevé pour un free_tier. "
            f"Risque d'atteinte des limites de débit (RPM/TPM)."
        )

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
    )


def simulate_fleet_budget(
    results: Sequence[SelectionResult],
    agents: Sequence[AgentRequirement],
    reference_paid_cost_per_m: float = 0.50,
) -> FleetBudgetReport:
    """Simule le coût total mensuel de l'ensemble des agents.

    Args:
        results: Résultats d'attribution de chaque agent.
        agents: Profils d'exigence des agents avec estimations de tokens.
        reference_paid_cost_per_m: Coût de référence payant par 1M tokens pour
            estimer les économies réalisées grâce au free_tier.

    Returns:
        FleetBudgetReport consolidé.
    """
    results_by_name = {r.agent_name: r for r in results}
    agent_reports: List[AgentBudgetReport] = []

    total_cost = 0.0
    total_tokens = 0
    free_tier_savings = 0.0

    for agent in agents:
        res = results_by_name.get(agent.name)
        model = res.model if res else None

        report = simulate_agent_budget(agent, model)
        agent_reports.append(report)

        total_cost += report.monthly_total_cost
        agent_tokens = report.estimated_input_tokens + report.estimated_output_tokens
        total_tokens += agent_tokens

        # Estimation des économies si modèle gratuit
        if model and model.is_free:
            savings = (agent_tokens / 1_000_000) * reference_paid_cost_per_m
            free_tier_savings += savings

    return FleetBudgetReport(
        total_monthly_cost=round(total_cost, 4),
        total_tokens=total_tokens,
        free_tier_savings=round(free_tier_savings, 4),
        agent_reports=agent_reports,
    )
