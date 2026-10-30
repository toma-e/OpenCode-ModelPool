"""Module d'export de la configuration pour les agents OpenCode.

Ce module transforme les résultats de sélection de modèles en un format
de configuration standardisé et exploitable par l'environnement OpenCode,
conforme au schéma officiel OpenCode (https://opencode.ai/config.json),
avec inclusion de la simulation budgétaire prévisionnelle.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from src.budget import simulate_fleet_budget
from src.selector import AgentRequirement, SelectionResult


# Préfixes de fournisseurs reconnus directement sans nécessiter le préfixe openrouter/
KNOWN_DIRECT_PROVIDERS = frozenset({
    "ollama", "mistral", "groq", "google", "anthropic", "cerebras"
})

# Commandes slash OpenCode déclarées nativement dans opencode.json
DEFAULT_OPENCODE_COMMANDS: Dict[str, Dict[str, Any]] = {
    "modelpool": {
        "description": "Statut ModelPool (modèles affectés, coûts et alertes)",
        "template": "Affiche le statut actuel de ModelPool en listant les modèles affectés à build, plan, explore et general ainsi que les alertes actives.",
    },
    "modelpool-sync": {
        "description": "Synchronisation du catalogue ModelPool et rafraîchissement d'OpenCode",
        "template": "Exécute la synchronisation du catalogue ModelPool (--sync-if-stale) et ré-exporte la configuration des modèles.",
    },
    "modelpool-failover": {
        "description": "Bascule un agent sur son modèle de repli en cas de quota ou saturation",
        "template": "Bascule l'agent $ARGUMENTS sur son modèle de secours ModelPool.",
    },
}



def format_opencode_model_id(
    model_id: str,
    default_prefix: str = "openrouter",
    base_config: Optional[Dict[str, Any]] = None,
) -> str:
    """Préfixe l'identifiant de modèle par le fournisseur attendu par OpenCode si nécessaire.

    Si le modèle appartient déjà à un provider déclaré dans base_config ou s'il provient
    d'un connecteur direct (ex: 'ollama', 'mistral', 'groq', 'google', 'anthropic', 'cerebras'),
    son identifiant est préservé sans forcer le préfixe default_prefix.

    Exemples:
        'openai/gpt-5-mini' -> 'openrouter/openai/gpt-5-mini'
        'ollama/qwen3.5:9b' -> 'ollama/qwen3.5:9b'
        'mistral/mistral-large-latest' -> 'mistral/mistral-large-latest'
        'openrouter/free' -> 'openrouter/free'
    """
    if not model_id:
        return model_id

    first_segment = model_id.split("/")[0] if "/" in model_id else ""

    # Si le modèle est déjà préfixé par un provider direct reconnu
    if first_segment in KNOWN_DIRECT_PROVIDERS:
        return model_id

    # Si le modèle commence déjà par un provider déclaré dans base_config["provider"]
    if base_config and isinstance(base_config.get("provider"), dict):
        configured_providers = set(base_config["provider"].keys())
        if first_segment in configured_providers:
            return model_id

    if default_prefix and not model_id.startswith(f"{default_prefix}/"):
        return f"{default_prefix}/{model_id}"
    return model_id


def parse_json_or_jsonc(content: str) -> Dict[str, Any]:
    """Parse une chaîne au format JSON ou JSONC (avec commentaires // et /* */ et trailing commas).

    Préserve rigoureusement le contenu des chaînes littérales (ex: URL avec // ou ponctuation).

    Args:
        content: Chaîne brute au format JSON ou JSONC.

    Returns:
        Dictionnaire Python désérialisé.

    Raises:
        ValueError: Si le contenu n'est pas un objet JSON valide.
    """
    # 1. Retrait des commentaires en préservant le contenu des chaînes littérales
    out: List[str] = []
    in_string = False
    escape = False
    in_single_line_comment = False
    in_multi_line_comment = False
    i = 0
    n = len(content)

    while i < n:
        char = content[i]
        next_char = content[i + 1] if i + 1 < n else ""

        if in_single_line_comment:
            if char in ("\r", "\n"):
                in_single_line_comment = False
                out.append(char)
            i += 1
            continue

        if in_multi_line_comment:
            if char == "*" and next_char == "/":
                in_multi_line_comment = False
                i += 2
            else:
                i += 1
            continue

        if in_string:
            out.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            i += 1
            continue

        if char == '"':
            in_string = True
            out.append(char)
            i += 1
        elif char == "/" and next_char == "/":
            in_single_line_comment = True
            i += 2
        elif char == "/" and next_char == "*":
            in_multi_line_comment = True
            i += 2
        else:
            out.append(char)
            i += 1

    no_comments = "".join(out)

    # 2. Retrait des virgules traînantes en préservant le contenu des chaînes littérales
    out2: List[str] = []
    in_string = False
    escape = False
    j = 0
    m = len(no_comments)
    while j < m:
        c = no_comments[j]
        if in_string:
            out2.append(c)
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_string = False
            j += 1
            continue

        if c == '"':
            in_string = True
            out2.append(c)
            j += 1
            continue

        if c == ",":
            # Vérifier si le prochain caractère non-blanc est '}' ou ']'
            k = j + 1
            while k < m and no_comments[k] in (" ", "\t", "\r", "\n"):
                k += 1
            if k < m and no_comments[k] in ("}", "]"):
                # Ignorer la virgule traînante
                j += 1
                continue

        out2.append(c)
        j += 1

    cleaned = "".join(out2)

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
    supports_vision: bool = False
    supports_reasoning: bool = False


@dataclass(frozen=True)
class OpenCodeAgentConfig:
    """Configuration complète d'un agent OpenCode (vue rapport OpenCode-ModelPool)."""

    name: str
    description: str
    enabled: bool
    requires_tools: bool
    min_context_window: Optional[int]
    allowed_providers: Optional[List[str]]
    max_monthly_budget: Optional[float]
    sort_strategy: str
    allow_free: bool
    requires_vision: bool
    requires_reasoning: bool
    prefer_tier1: bool
    estimated_monthly_cost: float
    model: Optional[OpenCodeModelConfig]
    selection_status: str
    selection_reason: str


def build_modelpool_report_data(
    results: Sequence[SelectionResult],
    agents: Sequence[AgentRequirement],
    fallback_chains: Optional[Dict[str, List[str]]] = None,
    execution_targets: Optional[Sequence[Optional[Any]]] = None,
) -> Dict[str, Any]:
    """Construit le rapport d'analyse et de simulation OpenCode-ModelPool."""
    agents_by_name = {a.name: a for a in agents}
    fleet_budget = simulate_fleet_budget(results, agents, execution_targets=execution_targets)
    budget_by_agent = {r.agent_name: r for r in fleet_budget.agent_reports}

    configured_agents: Dict[str, Dict[str, Any]] = {}
    assigned_count = 0
    unassigned_count = 0

    for res in results:
        agent_req = agents_by_name.get(res.agent_name)
        description = agent_req.description if agent_req else ""
        requires_tools = agent_req.requires_tools if agent_req else False
        min_context = agent_req.min_context_window if agent_req else None
        allowed_providers = agent_req.allowed_providers if agent_req else None
        max_budget = agent_req.max_monthly_budget if agent_req else None
        sort_strategy = agent_req.sort_strategy if agent_req else "lowest_cost"
        allow_free = agent_req.allow_free if agent_req else True
        requires_vision = agent_req.requires_vision if agent_req else False
        requires_reasoning = agent_req.requires_reasoning if agent_req else False
        prefer_tier1 = agent_req.prefer_tier1 if agent_req else True

        agent_budget = budget_by_agent.get(res.agent_name)
        monthly_cost = agent_budget.monthly_total_cost if agent_budget else 0.0

        if res.model:
            assigned_count += 1
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
                supports_vision=res.model.supports_vision,
                supports_reasoning=res.model.supports_reasoning,
            )
            agent_conf = OpenCodeAgentConfig(
                name=res.agent_name,
                description=description,
                enabled=True,
                requires_tools=requires_tools,
                min_context_window=min_context,
                allowed_providers=allowed_providers,
                max_monthly_budget=max_budget,
                sort_strategy=sort_strategy,
                allow_free=allow_free,
                requires_vision=requires_vision,
                requires_reasoning=requires_reasoning,
                prefer_tier1=prefer_tier1,
                estimated_monthly_cost=monthly_cost,
                model=model_conf,
                selection_status=status_str,
                selection_reason=res.reason,
            )
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
                sort_strategy=sort_strategy,
                allow_free=allow_free,
                requires_vision=requires_vision,
                requires_reasoning=requires_reasoning,
                prefer_tier1=prefer_tier1,
                estimated_monthly_cost=0.0,
                model=None,
                selection_status="unassigned",
                selection_reason=res.reason,
            )

        agent_dict = asdict(agent_conf)
        # Chaîne de repli ordonnée (limites de débit / quotas) pour les plugins OpenCode de bascule
        agent_dict["fallback_chain"] = list((fallback_chains or {}).get(res.agent_name, []))
        configured_agents[res.agent_name] = agent_dict

    budget_summary = {
        "total_estimated_monthly_cost": fleet_budget.total_monthly_cost,
        "total_estimated_tokens": fleet_budget.total_tokens,
        "estimated_free_tier_savings": fleet_budget.free_tier_savings,
        "has_warnings": fleet_budget.has_budget_warnings,
        "is_total_estimable": fleet_budget.is_total_estimable,
        "reports": [
            {
                "agent": r.agent_name,
                "monthly_cost": r.monthly_total_cost if r.is_estimable else None,
                "monthly_cost_formatted": f"${r.monthly_total_cost:.4f}" if r.is_estimable else "Non estimable",
                "is_estimable": r.is_estimable,
                "input_cost": r.monthly_input_cost if r.is_estimable else None,
                "output_cost": r.monthly_output_cost if r.is_estimable else None,
                "max_budget": r.max_budget,
                "budget_exceeded": r.budget_exceeded,
                "quota_warning": r.quota_warning,
                "channel_provider": r.channel_provider,
                "pricing_source": r.pricing_source,
                "is_local": r.is_local,
                "disclaimer": r.disclaimer,
            }
            for r in fleet_budget.agent_reports
        ],
    }

    return {
        "version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "metadata": {
            "generator": "OpenCode-ModelPool",
            "total_agents": len(results),
            "assigned_agents": assigned_count,
            "unassigned_agents": unassigned_count,
        },
        "budget_simulation": budget_summary,
        "agents": configured_agents,
    }


# Alias de rétrocompatibilité
build_modelscope_report_data = build_modelpool_report_data


def build_opencode_config(
    results: Sequence[SelectionResult],
    agents: Sequence[AgentRequirement],
    base_config: Optional[Dict[str, Any]] = None,
    default_provider_prefix: str = "openrouter",
    enable_fallback_plugin: bool = True,
    enable_commands: bool = False,
    mcp_servers: Optional[Dict[str, Any]] = None,
    local_plugin_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Construit le dictionnaire de configuration strictement conforme au schéma OpenCode.

    Ne produit que les clés autorisées par OpenCode (https://opencode.ai/config.json).
    Les métadonnées de simulation d'OpenCode-ModelPool sont exportées dans un rapport séparé.

    Args:
        results: Résultats de la sélection pour chaque agent.
        agents: Exigences initiales des agents.
        base_config: Configuration OpenCode de base optionnelle à enrichir (ex: permissions, providers).
        default_provider_prefix: Préfixe du fournisseur OpenCode pour router les modèles (défaut 'openrouter').
        enable_fallback_plugin: Active le plugin de repli automatique sur erreur (@azumag/opencode-rate-limit-fallback).
        enable_commands: Déclare les commandes slash OpenCode (/modelpool, /modelpool-sync, /modelpool-failover).
        mcp_servers: Serveurs Model Context Protocol (MCP) à déclarer sous la clé 'mcp'.
        local_plugin_path: Chemin relatif ou absolu d'un plugin local à inclure dans 'plugins'.

    Returns:
        Dictionnaire conforme au schéma officiel OpenCode.
    """
    agents_by_name = {a.name: a for a in agents}
    opencode_agent_configs: Dict[str, Dict[str, Any]] = {}
    first_assigned_model_id: Optional[str] = None

    for res in results:
        agent_req = agents_by_name.get(res.agent_name)
        description = agent_req.description if agent_req else ""

        if res.model:
            formatted_model_id = format_opencode_model_id(
                res.model.id,
                default_prefix=default_provider_prefix,
                base_config=base_config,
            )
            if first_assigned_model_id is None:
                first_assigned_model_id = formatted_model_id

            # Choix du mode : spécifié par l'agent, sinon heuristique
            if agent_req and agent_req.mode:
                agent_mode = agent_req.mode
            elif res.agent_name in {"build", "plan", "coder_agent", "orchestrator", "orchestrator-free"}:
                agent_mode = "primary"
            else:
                agent_mode = "subagent"

            native_agent: Dict[str, Any] = {
                "model": formatted_model_id,
                "mode": agent_mode,
            }
            if description:
                native_agent["description"] = description
            # MP-205 : Permissions différenciées selon le rôle d'agent OpenCode
            if res.agent_name in {"plan", "explore"}:
                native_agent["permission"] = {"edit": "deny"}
            elif res.agent_name == "build":
                native_agent["permission"] = {"edit": "allow"}
            opencode_agent_configs[res.agent_name] = native_agent
        else:
            native_unassigned: Dict[str, Any] = {
                "disable": True,
            }
            if description:
                native_unassigned["description"] = description
            opencode_agent_configs[res.agent_name] = native_unassigned

    # Initialisation à partir de la configuration de base si fournie
    final_config: Dict[str, Any] = dict(base_config) if base_config else {}

    # Schéma officiel OpenCode
    final_config["$schema"] = "https://opencode.ai/config.json"

    # Modèle par défaut OpenCode (MP-206 : éviter qu'un défaut inaccessible comme openrouter/free reste actif)
    if "model" not in final_config:
        if first_assigned_model_id:
            final_config["model"] = first_assigned_model_id
    elif final_config.get("model") in {"openrouter/free", "openrouter/:free"} and first_assigned_model_id:
        final_config["model"] = first_assigned_model_id

    # Fusion des agents natifs dans la clé "agent" attendue par OpenCode
    existing_native_agents = dict(final_config.get("agent", {})) if isinstance(final_config.get("agent"), dict) else {}
    existing_native_agents.update(opencode_agent_configs)
    final_config["agent"] = existing_native_agents

    # Enregistrement automatique du plugin de repli d'OpenCode (Rate-limit / Quota / 504 Timeout)
    fallback_plugin_pkg = "@azumag/opencode-rate-limit-fallback"
    if enable_fallback_plugin:
        if "plugins" in final_config and isinstance(final_config["plugins"], list):
            if fallback_plugin_pkg not in final_config["plugins"] and not any(
                isinstance(p, str) and p.startswith(fallback_plugin_pkg) for p in final_config["plugins"]
            ):
                final_config["plugins"].append(fallback_plugin_pkg)
        elif "plugin" in final_config and isinstance(final_config["plugin"], list):
            if fallback_plugin_pkg not in final_config["plugin"] and not any(
                isinstance(p, str) and p.startswith(fallback_plugin_pkg) for p in final_config["plugin"]
            ):
                final_config["plugin"].append(fallback_plugin_pkg)
        else:
            final_config["plugin"] = [fallback_plugin_pkg]

    # Enregistrement d'un plugin local personnalisé (ex: ./plugins/modelpool.mjs)
    if local_plugin_path:
        target_plugin_key = "plugins" if "plugins" in final_config else "plugin"
        curr_plugins = list(final_config.get(target_plugin_key, [])) if isinstance(final_config.get(target_plugin_key), list) else []
        if local_plugin_path not in curr_plugins and not any(
            isinstance(p, str) and p.endswith(local_plugin_path.lstrip("./")) for p in curr_plugins
        ):
            curr_plugins.append(local_plugin_path)
        final_config[target_plugin_key] = curr_plugins

    # Enregistrement des commandes slash OpenCode
    if enable_commands:
        existing_commands = dict(final_config.get("command", {})) if isinstance(final_config.get("command"), dict) else {}
        for cmd_name, cmd_body in DEFAULT_OPENCODE_COMMANDS.items():
            if cmd_name not in existing_commands:
                existing_commands[cmd_name] = dict(cmd_body)
        final_config["command"] = existing_commands

    # Enregistrement des serveurs MCP
    if mcp_servers:
        existing_mcp = dict(final_config.get("mcp", {})) if isinstance(final_config.get("mcp"), dict) else {}
        existing_mcp.update(mcp_servers)
        final_config["mcp"] = existing_mcp

    return final_config


def validate_opencode_config(config: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Valide la structure d'une configuration générée par rapport au schéma OpenCode officiel.

    Returns:
        Tuple (est_valide, liste_erreurs).
    """
    errors: List[str] = []
    if not isinstance(config, dict):
        return False, ["La configuration doit être un dictionnaire JSON."]

    schema = config.get("$schema")
    if not schema or not isinstance(schema, str) or not schema.startswith("https://opencode.ai/"):
        errors.append("Clé '$schema' manquante ou invalide (doit pointer vers https://opencode.ai/config.json).")

    model = config.get("model")
    if not model or not isinstance(model, str):
        errors.append("Clé 'model' par défaut manquante ou non textuelle.")

    agents = config.get("agent")
    if not isinstance(agents, dict) or not agents:
        errors.append("Section 'agent' manquante ou vide.")
    else:
        for name, conf in agents.items():
            if not isinstance(conf, dict):
                errors.append(f"Agent '{name}' : configuration invalide (doit être un objet).")
                continue
            if conf.get("disable") is True:
                continue
            agent_model = conf.get("model")
            if not agent_model or not isinstance(agent_model, str):
                errors.append(f"Agent '{name}' : 'model' manquant ou invalide.")
            agent_mode = conf.get("mode")
            if agent_mode not in {"primary", "subagent", "all"}:
                errors.append(f"Agent '{name}' : 'mode' invalide ('{agent_mode}' non reconnu).")

    return len(errors) == 0, errors


def split_opencode_model_id(
    formatted_id: str,
    default_provider: str = "openrouter",
) -> Tuple[str, str]:
    """Découpe un identifiant de modèle OpenCode en couple ``(providerID, modelID)``.

    Exemples:
        'openrouter/nvidia/nemotron-3-ultra-550b-a55b:free' -> ('openrouter', 'nvidia/nemotron-3-ultra-550b-a55b:free')
        'groq/openai/gpt-oss-120b' -> ('groq', 'openai/gpt-oss-120b')
        'ollama/qwen3.5:9b' -> ('ollama', 'qwen3.5:9b')
        'openai/gpt-5-mini' -> ('openrouter', 'openai/gpt-5-mini')
    """
    clean = (formatted_id or "").strip()
    if not clean:
        return default_provider, ""
    if "/" not in clean:
        return default_provider, clean

    first, rest = clean.split("/", 1)
    known_prefixes = set(KNOWN_DIRECT_PROVIDERS) | {"openrouter"}
    if first.lower() in known_prefixes:
        return first.lower(), rest
    return default_provider, clean


def build_rate_limit_fallback_config(
    results: Sequence[SelectionResult],
    fallback_chains: Optional[Mapping[str, Sequence[str]]] = None,
    cooldown_ms: int = 900_000,
) -> Dict[str, Any]:
    """Construit la configuration JSON standardisée pour le repli automatique sur limite de débit.

    Compatible avec ``@azumag/opencode-rate-limit-fallback`` (``rate-limit-fallback.json``)
    et le plugin local généré par OpenCode-ModelPool.
    """
    chains = fallback_chains or {}
    global_models: List[Dict[str, str]] = []
    seen_global: set[Tuple[str, str]] = set()
    agent_fallbacks: Dict[str, List[Dict[str, str]]] = {}

    for res in results:
        agent_chain = chains.get(res.agent_name, [])
        entries: List[Dict[str, str]] = []
        seen_agent: set[Tuple[str, str]] = set()
        for formatted_id in agent_chain:
            prov_id, mod_id = split_opencode_model_id(formatted_id)
            if not mod_id:
                continue
            pair = (prov_id, mod_id)
            if pair not in seen_agent:
                seen_agent.add(pair)
                entries.append({"providerID": prov_id, "modelID": mod_id})
            if pair not in seen_global:
                seen_global.add(pair)
                global_models.append({"providerID": prov_id, "modelID": mod_id})
        agent_fallbacks[res.agent_name] = entries

    return {
        "enabled": True,
        "fallbackModels": global_models,
        "agentFallbackModels": agent_fallbacks,
        "fallbackMode": "cycle",
        "cooldownMs": cooldown_ms,
        "retryPolicy": {
            "maxRetries": 2,
            "strategy": "exponential",
            "baseDelayMs": 500,
            "maxDelayMs": 5000,
            "jitterEnabled": True,
            "jitterFactor": 0.1,
            "timeoutMs": 30000,
        },
        "enableSubagentFallback": True,
        "maxSubagentDepth": 10,
        "patterns": [
            "rate limit",
            "rate_limit",
            "usage limit",
            "too many requests",
            "429",
            "quota exceeded",
            "resource_exhausted",
            "insufficient credits",
            "payment required",
            "402",
            "overloaded",
            "service unavailable",
            "503",
            "504",
            "upstream idle timeout",
            "idle timeout",
            "gateway timeout",
            "timeout",
            "stream error",
            "connection reset",
        ],
    }


def build_opencode_fallback_plugin_js(
    results: Sequence[SelectionResult],
    fallback_chains: Optional[Mapping[str, Sequence[str]]] = None,
    project_dir: str = "",
    export_path: str = "config/opencode.json",
) -> str:
    """Génère le code JavaScript ESM autonome du plugin OpenCode de repli à chaud.

    Ce plugin s'exécute directement dans OpenCode :
    1. Il intercepte les événements ``session.error`` et ``session.status`` (429, quota, 402, 503).
    2. Il interrompt l'attente bloquée (``client.session.abort``), choisit le modèle suivant
       dans la ``fallback_chain`` de l'agent ou du modèle actif, et relance automatiquement
       le dernier prompt utilisateur avec le modèle de secours (``client.session.prompt``).
    3. En tâche de fond, il appelle ``main.py --failover`` pour placer le modèle défaillant
       en quarantaine dans ``data/model_cooldowns.json`` et mettre à jour ``opencode.json``.
    """
    fallback_cfg = build_rate_limit_fallback_config(results, fallback_chains=fallback_chains)
    model_to_chain: Dict[str, List[Dict[str, str]]] = {}
    for res in results:
        if not res.model:
            continue
        formatted_primary = format_opencode_model_id(res.model.id)
        agent_entries = fallback_cfg["agentFallbackModels"].get(res.agent_name, [])
        if agent_entries:
            model_to_chain[formatted_primary] = agent_entries
            model_to_chain[res.model.id] = agent_entries

    embedded_config = json.dumps(
        {
            "fallbackModels": fallback_cfg["fallbackModels"],
            "agentFallbackModels": fallback_cfg["agentFallbackModels"],
            "modelToChain": model_to_chain,
            "cooldownMs": fallback_cfg["cooldownMs"],
            "patterns": fallback_cfg["patterns"],
            "projectDir": project_dir,
            "exportPath": export_path,
        },
        indent=2,
        ensure_ascii=False,
    )

    return f"""// Plugin auto-généré par OpenCode-ModelPool — Repli automatique sur erreur (429 / Quota / 503)
import {{ spawn }} from "node:child_process";
import path from "node:path";

const CONFIG = {embedded_config};

function classifyErrorReason(text) {{
  const lower = String(text || "").toLowerCase();
  if (lower.includes("402") || lower.includes("insufficient credits") || lower.includes("payment required") || lower.includes("billing")) {{
    return "insufficient_credits";
  }}
  if (lower.includes("quota exceeded") || lower.includes("daily limit") || lower.includes("resource_exhausted") || lower.includes("usage limit")) {{
    return "quota_exceeded";
  }}
  if (lower.includes("429") || lower.includes("rate limit") || lower.includes("rate_limit") || lower.includes("too many requests")) {{
    return "rate_limit";
  }}
  if (lower.includes("504") || lower.includes("upstream idle timeout") || lower.includes("idle timeout") || lower.includes("gateway timeout") || lower.includes("stream error") || lower.includes("503") || lower.includes("502") || lower.includes("overloaded") || lower.includes("service unavailable") || lower.includes("timeout")) {{
    return "service_unavailable";
  }}
  return null;
}}

function matchesFallbackPattern(text) {{
  const lower = String(text || "").toLowerCase();
  if (!lower) return false;
  return CONFIG.patterns.some((p) => lower.includes(p));
}}

function notifyModelPoolQuarantine(failedTarget, errorReason) {{
  if (!CONFIG.projectDir || !failedTarget) return;
  try {{
    const mainScript = path.join(CONFIG.projectDir, "main.py");
    const args = [
      mainScript,
      "--failover",
      failedTarget,
      "--error-reason",
      errorReason || "rate_limit",
      "--export",
      CONFIG.exportPath || "config/opencode.json",
    ];
    const child = spawn("python3", args, {{
      cwd: CONFIG.projectDir,
      stdio: "ignore",
      detached: true,
    }});
    child.unref();
  }} catch (_err) {{
    // Ne jamais bloquer la session OpenCode si l'appel d'arrière-plan échoue
  }}
}}

let checkedStale = false;
function checkStaleCatalog() {{
  if (checkedStale || !CONFIG.projectDir) return;
  checkedStale = true;
  try {{
    const mainScript = path.join(CONFIG.projectDir, "main.py");
    const args = [
      mainScript,
      "--sync-if-stale",
      "14",
      "--export",
      CONFIG.exportPath || "config/opencode.json",
    ];
    const child = spawn("python3", args, {{
      cwd: CONFIG.projectDir,
      stdio: "ignore",
      detached: true,
    }});
    child.unref();
  }} catch (_err) {{
    // Ne jamais bloquer la session OpenCode si l'appel d'arrière-plan échoue
  }}
}}

export const ModelPoolFallbackPlugin = async ({{ client }}) => {{
  const cooldownUntil = new Map();
  const activeHandling = new Set();

  function isCoolingDown(providerID, modelID) {{
    const key = `${{providerID}}/${{modelID}}`;
    const exp = cooldownUntil.get(key);
    if (!exp) return false;
    if (Date.now() >= exp) {{
      cooldownUntil.delete(key);
      return false;
    }}
    return true;
  }}

  function markCooldown(providerID, modelID) {{
    const key = `${{providerID}}/${{modelID}}`;
    cooldownUntil.set(key, Date.now() + (CONFIG.cooldownMs || 900000));
  }}

  function pickNextModel(agentName, currentModelKey) {{
    const candidates = [
      ...(CONFIG.agentFallbackModels[agentName] || []),
      ...(CONFIG.modelToChain[currentModelKey] || []),
      ...(CONFIG.fallbackModels || []),
    ];
    for (const item of candidates) {{
      const key = `${{item.providerID}}/${{item.modelID}}`;
      if (key !== currentModelKey && !isCoolingDown(item.providerID, item.modelID)) {{
        return item;
      }}
    }}
    return null;
  }}

  async function handleRateLimitOrError(sessionID, errorText, currentAgent, currentProviderID, currentModelID) {{
    if (!sessionID || activeHandling.has(sessionID)) return;
    if (!matchesFallbackPattern(errorText)) return;

    activeHandling.add(sessionID);
    try {{
      const reason = classifyErrorReason(errorText) || "rate_limit";
      const currentKey = currentProviderID && currentModelID ? `${{currentProviderID}}/${{currentModelID}}` : "";
      if (currentProviderID && currentModelID) {{
        markCooldown(currentProviderID, currentModelID);
      }}

      notifyModelPoolQuarantine(currentAgent || currentKey, reason);

      const nextModel = pickNextModel(currentAgent || "build", currentKey);
      if (!nextModel || !client?.session) return;

      try {{
        await client.session.abort({{ path: {{ id: sessionID }} }});
      }} catch (_e) {{}}

      let lastText = "Continue la tâche en cours.";
      try {{
        const msgs = await client.session.messages({{ path: {{ id: sessionID }} }});
        const list = Array.isArray(msgs?.data) ? msgs.data : (Array.isArray(msgs) ? msgs : []);
        for (let i = list.length - 1; i >= 0; i--) {{
          const m = list[i];
          if (m?.info?.role === "user" || m?.role === "user") {{
            const parts = m?.parts || m?.info?.parts || [];
            const textPart = parts.find((p) => p?.type === "text" && p?.text);
            if (textPart?.text) {{
              lastText = textPart.text;
              break;
            }}
          }}
        }}
      }} catch (_e) {{}}

      await client.session.prompt({{
        path: {{ id: sessionID }},
        body: {{
          model: {{
            providerID: nextModel.providerID,
            modelID: nextModel.modelID,
          }},
          parts: [{{ type: "text", text: lastText }}],
        }},
      }});
    }} finally {{
      setTimeout(() => activeHandling.delete(sessionID), 2500);
    }}
  }}

  return {{
    event: async ({{ event }}) => {{
      if (!event || !event.type) return;
      if (event.type === "session.created" || event.type === "session.start") {{
        checkStaleCatalog();
      }}
      const props = event.properties || event.data || event || {{}};
      const sessionID = props.sessionID || props.id || props.session?.id || event.sessionID || event.session?.id;
      const agent = props.agent || event.agent;
      const providerID = props.providerID || event.providerID;
      const modelID = props.modelID || event.modelID;

      if (event.type === "session.error") {{
        const errObj = props.error || event.error || {{}};
        const errText = typeof errObj === "string" ? errObj : JSON.stringify(errObj);
        await handleRateLimitOrError(
          sessionID,
          errText,
          agent,
          providerID,
          modelID
        );
      }} else if (event.type === "session.status") {{
        const status = props.status || event.status || {{}};
        const msg = status.message || (typeof status === "string" ? status : "");
        if (status.type === "retry" || status.type === "error" || msg) {{
          await handleRateLimitOrError(
            sessionID,
            msg || JSON.stringify(status),
            agent,
            providerID,
            modelID
          );
        }}
      }}
    }},
  }};
}};

export default ModelPoolFallbackPlugin;
"""


