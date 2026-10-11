"""Module d'export de la configuration pour les agents OpenCode.

Ce module transforme les résultats de sélection de modèles en un format
de configuration standardisé et exploitable par l'environnement OpenCode,
conforme au schéma officiel OpenCode (https://opencode.ai/config.json),
avec inclusion de la simulation budgétaire prévisionnelle.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from src.budget import simulate_fleet_budget
from src.selector import AgentRequirement, SelectionResult


def parse_json_or_jsonc(content: str) -> Dict[str, Any]:
    """Parse une chaîne au format JSON ou JSONC (avec commentaires // et /* */).

    Args:
        content: Chaîne brute au format JSON ou JSONC.

    Returns:
        Dictionnaire Python désérialisé.

    Raises:
        ValueError: Si le contenu n'est pas un objet JSON valide.
    """
    # Retrait des commentaires multi-lignes /* ... */
    cleaned = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)
    # Retrait des commentaires mono-lignes //
    lines: List[str] = []
    for line in cleaned.splitlines():
        lines.append(re.sub(r"(?<!:)//.*$", "", line))
    cleaned = "\n".join(lines)
    # Retrait des virgules traînantes devant une fermeture d'accolade ou de crochet
    cleaned = re.sub(r",\s*([\]}])", r"\1", cleaned)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as error:
        raise ValueError(f"Impossible de parser le document JSON(C) : {error}") from error

    if not isinstance(data, dict):
        raise ValueError("Le document JSON(C) doit avoir un objet comme racine.")
    return data


@dataclass(frozen=True)
class OpenCodeModelConfig:
    """Configuration du modèle attribué à un agent OpenCode."""

    id: str
    provider: str
    tier: str
    context_window: int
    supports_tools: bool
    cost_input_per_m: float
    cost_output_per_m: float
    total_cost_per_m: float


@dataclass(frozen=True)
class OpenCodeAgentConfig:
    """Configuration complète d'un agent OpenCode."""

    name: str
    description: str
    enabled: bool
    requires_tools: bool
    min_context_window: Optional[int]
    allowed_providers: Optional[List[str]]
    max_monthly_budget: Optional[float]
    estimated_monthly_cost: float
    model: Optional[OpenCodeModelConfig]
    selection_status: str
    selection_reason: str


def build_opencode_config(
    results: Sequence[SelectionResult],
    agents: Sequence[AgentRequirement],
    base_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Construit le dictionnaire de configuration pour OpenCode.

    Génère les sections conformes au schéma officiel OpenCode (https://opencode.ai/config.json),
    notamment `$schema`, `model`, `agent`, tout en préservant les sections existantes
    (ex: `permission`, `provider`) et les métadonnées de simulation de ModelScope.

    Args:
        results: Résultats de la sélection pour chaque agent.
        agents: Exigences initiales des agents.
        base_config: Configuration OpenCode de base optionnelle à enrichir (ex: permissions, providers).

    Returns:
        Dictionnaire au format OpenCode contenant les agents configurés,
        les métadonnées et la simulation budgétaire consolidée.
    """
    agents_by_name = {a.name: a for a in agents}
    fleet_budget = simulate_fleet_budget(results, agents)
    budget_by_agent = {r.agent_name: r for r in fleet_budget.agent_reports}

    configured_agents: Dict[str, Dict[str, Any]] = {}
    opencode_agent_configs: Dict[str, Dict[str, Any]] = {}
    assigned_count = 0
    unassigned_count = 0
    first_assigned_model_id: Optional[str] = None

    for res in results:
        agent_req = agents_by_name.get(res.agent_name)
        description = agent_req.description if agent_req else ""
        requires_tools = agent_req.requires_tools if agent_req else False
        min_context = agent_req.min_context_window if agent_req else None
        allowed_providers = agent_req.allowed_providers if agent_req else None
        max_budget = agent_req.max_monthly_budget if agent_req else None

        agent_budget = budget_by_agent.get(res.agent_name)
        monthly_cost = agent_budget.monthly_total_cost if agent_budget else 0.0

        if res.model:
            assigned_count += 1
            if first_assigned_model_id is None:
                first_assigned_model_id = res.model.id
            status_str = "fallback" if res.is_fallback else "exact"
            model_conf = OpenCodeModelConfig(
                id=res.model.id,
                provider=res.model.provider,
                tier=res.model.tier,
                context_window=res.model.context_window,
                supports_tools=res.model.supports_tools,
                cost_input_per_m=res.model.cost_input_per_m,
                cost_output_per_m=res.model.cost_output_per_m,
                total_cost_per_m=res.model.total_cost_per_m,
            )
            agent_conf = OpenCodeAgentConfig(
                name=res.agent_name,
                description=description,
                enabled=True,
                requires_tools=requires_tools,
                min_context_window=min_context,
                allowed_providers=allowed_providers,
                max_monthly_budget=max_budget,
                estimated_monthly_cost=monthly_cost,
                model=model_conf,
                selection_status=status_str,
                selection_reason=res.reason,
            )
            # Configuration native attendue par OpenCode (agent[name])
            agent_mode = "primary" if res.agent_name in {"coder_agent", "build", "orchestrator", "orchestrator-free"} else "subagent"
            native_agent: Dict[str, Any] = {
                "model": res.model.id,
                "mode": agent_mode,
            }
            if description:
                native_agent["description"] = description
            opencode_agent_configs[res.agent_name] = native_agent
        else:
            unassigned_count += 1
            agent_conf = OpenCodeAgentConfig(
                name=res.agent_name,
                description=description,
                enabled=False,
                requires_tools=requires_tools,
                min_context_window=min_context,
                allowed_providers=allowed_providers,
                max_monthly_budget=max_budget,
                estimated_monthly_cost=0.0,
                model=None,
                selection_status="unassigned",
                selection_reason=res.reason,
            )
            native_unassigned: Dict[str, Any] = {
                "disable": True,
            }
            if description:
                native_unassigned["description"] = description
            opencode_agent_configs[res.agent_name] = native_unassigned

        configured_agents[res.agent_name] = asdict(agent_conf)

    budget_summary = {
        "total_estimated_monthly_cost": fleet_budget.total_monthly_cost,
        "total_estimated_tokens": fleet_budget.total_tokens,
        "estimated_free_tier_savings": fleet_budget.free_tier_savings,
        "has_warnings": fleet_budget.has_budget_warnings,
        "reports": [
            {
                "agent": r.agent_name,
                "monthly_cost": r.monthly_total_cost,
                "input_cost": r.monthly_input_cost,
                "output_cost": r.monthly_output_cost,
                "max_budget": r.max_budget,
                "budget_exceeded": r.budget_exceeded,
                "quota_warning": r.quota_warning,
            }
            for r in fleet_budget.agent_reports
        ],
    }

    # Initialisation à partir de la configuration de base si fournie
    final_config: Dict[str, Any] = dict(base_config) if base_config else {}

    # Schéma officiel OpenCode
    final_config["$schema"] = "https://opencode.ai/config.json"

    # Modèle par défaut OpenCode (conservé si déjà défini, sinon premier modèle assigné)
    if "model" not in final_config and first_assigned_model_id:
        final_config["model"] = first_assigned_model_id

    # Fusion des agents natifs dans la clé "agent" attendue par OpenCode
    existing_native_agents = dict(final_config.get("agent", {})) if isinstance(final_config.get("agent"), dict) else {}
    existing_native_agents.update(opencode_agent_configs)
    final_config["agent"] = existing_native_agents

    # Métadonnées et simulation de ModelScope (rétrocompatibilité et auditabilité)
    final_config["version"] = "1.0"
    final_config["generated_at"] = datetime.now(timezone.utc).isoformat()
    final_config["metadata"] = {
        "generator": "ModelScope",
        "total_agents": len(results),
        "assigned_agents": assigned_count,
        "unassigned_agents": unassigned_count,
    }
    final_config["budget_simulation"] = budget_summary
    final_config["agents"] = configured_agents

    return final_config


def export_opencode_config(
    results: Sequence[SelectionResult],
    agents: Sequence[AgentRequirement],
    output_path: Path,
    base_config: Optional[Dict[str, Any]] = None,
) -> Path:
    """Génère et sauvegarde le fichier de configuration JSON pour OpenCode.

    Args:
        results: Résultats de la sélection des modèles.
        agents: Exigences initiales des agents.
        output_path: Fichier de destination (ex: config/opencode.json).
        base_config: Configuration OpenCode de base optionnelle à fusionner.

    Returns:
        Chemin absolu du fichier écrit.
    """
    config_data = build_opencode_config(results, agents, base_config=base_config)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2, ensure_ascii=False)

    return output_path.resolve()
