"""Sélection pure et validation des modèles LLM pour les agents."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Optional, Sequence


# Fournisseurs de référence (Tier 1) mondialement reconnus pour la qualité de code et d'ingénierie
TIER1_PROVIDERS: frozenset[str] = frozenset({
    "anthropic",
    "openai",
    "google",
    "deepseek",
    "mistralai",
    "meta",
    "meta-llama",
    "qwen",
})


def _required(data: dict[str, Any], field: str, context: str) -> Any:
    if field not in data:
        raise ValueError(f"{context}: champ obligatoire '{field}' absent.")
    return data[field]


def _bool(value: Any, field: str, context: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{context}: '{field}' doit être un booléen.")
    return value


def _int(value: Any, field: str, context: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{context}: '{field}' doit être un entier supérieur ou égal à {minimum}.")
    return value


def _number(value: Any, field: str, context: str, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < minimum:
        raise ValueError(f"{context}: '{field}' doit être un nombre fini supérieur ou égal à {minimum}.")
    return float(value)


@dataclass(frozen=True)
class Model:
    """Représentation validée d'un modèle disponible dans le catalogue."""

    id: str
    provider: str
    tier: str
    cost_input_per_m: float
    cost_output_per_m: float
    context_window: int
    supports_tools: bool
    complexity_score: int
    supports_vision: bool = False
    supports_reasoning: bool = False

    @property
    def is_free(self) -> bool:
        """Indique si le modèle appartient au niveau gratuit."""
        return self.tier == "free_tier" or (
            self.cost_input_per_m == 0.0 and self.cost_output_per_m == 0.0
        )

    @property
    def total_cost_per_m(self) -> float:
        """Somme des coûts d'entrée et de sortie par million de tokens."""
        return self.cost_input_per_m + self.cost_output_per_m

    def calculate_cost(self, input_tokens: int, output_tokens: int) -> tuple[float, float, float]:
        """Calcule les coûts d'entrée, de sortie et total pour un volume de tokens donné, arrondis à 4 décimales."""
        cost_in = (input_tokens / 1_000_000) * self.cost_input_per_m
        cost_out = (output_tokens / 1_000_000) * self.cost_output_per_m
        return round(cost_in, 4), round(cost_out, 4), round(cost_in + cost_out, 4)

    @classmethod
    def from_dict(cls, data: dict[str, Any], context: str = "modèle") -> Model:
        """Instancie un modèle après validation stricte de son dictionnaire."""
        model_id = _required(data, "id", context)
        provider = _required(data, "provider", context)
        tier = _required(data, "tier", context)
        if not all(isinstance(value, str) and value for value in (model_id, provider, tier)):
            raise ValueError(f"{context}: 'id', 'provider' et 'tier' doivent être des chaînes non vides.")
        if tier not in {"free_tier", "pay_as_you_go"}:
            raise ValueError(f"{context}: 'tier' doit être 'free_tier' ou 'pay_as_you_go'.")
        complexity = _int(_required(data, "complexity_score", context), "complexity_score", context, 1)
        if complexity > 5:
            raise ValueError(f"{context}: 'complexity_score' doit être compris entre 1 et 5.")
        model_id_lower = model_id.lower()
        if "supports_vision" in data:
            supports_vision = _bool(data["supports_vision"], "supports_vision", context)
        else:
            vision_keywords = (
                "-vl", "-vision", "vision-", "/vision", "omni",
                "gpt-4", "gpt-5", "gpt-6", "gemini-", "claude-",
                "openai/o1", "openai/o3", "openai/o4"
            )
            supports_vision = any(kw in model_id_lower for kw in vision_keywords)

        if "supports_reasoning" in data:
            supports_reasoning = _bool(data["supports_reasoning"], "supports_reasoning", context)
        else:
            reasoning_keywords = ("o1", "o3", "o4", "r1", "qwq", "thinking", "reasoning", "reasoner")
            supports_reasoning = any(
                re.search(rf"(?:^|[-_/:])({re.escape(kw)})(?:$|[-_/:])", model_id_lower)
                for kw in reasoning_keywords
            )

        return cls(
            id=model_id,
            provider=provider,
            tier=tier,
            cost_input_per_m=_number(_required(data, "cost_input_per_m", context), "cost_input_per_m", context),
            cost_output_per_m=_number(_required(data, "cost_output_per_m", context), "cost_output_per_m", context),
            context_window=_int(_required(data, "context_window", context), "context_window", context, 1),
            supports_tools=_bool(_required(data, "supports_tools", context), "supports_tools", context),
            complexity_score=complexity,
            supports_vision=supports_vision,
            supports_reasoning=supports_reasoning,
        )


@dataclass(frozen=True)
class AgentRequirement:
    """Spécification validée des besoins techniques et budgétaires d'un agent."""

    name: str
    description: str
    min_complexity: int
    max_complexity: int
    requires_tools: bool
    prefer_free: bool
    min_context_window: Optional[int] = None
    allowed_providers: Optional[list[str]] = None
    excluded_providers: Optional[list[str]] = None
    force_model: Optional[str] = None
    mode: Optional[str] = None
    estimated_tokens_input: int = 0
    estimated_tokens_output: int = 0
    max_monthly_budget: Optional[float] = None
    sort_strategy: str = "lowest_cost"
    allow_free: bool = True
    requires_vision: bool = False
    requires_reasoning: bool = False
    prefer_tier1: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any], context: str = "agent") -> AgentRequirement:
        """Instancie un agent après validation stricte de son dictionnaire."""
        name = _required(data, "name", context)
        if not isinstance(name, str) or not name:
            raise ValueError(f"{context}: 'name' doit être une chaîne non vide.")
        description = data.get("description", "")
        if not isinstance(description, str):
            raise ValueError(f"{context}: 'description' doit être une chaîne.")
        minimum = _int(_required(data, "min_complexity", context), "min_complexity", context, 1)
        maximum = _int(_required(data, "max_complexity", context), "max_complexity", context, 1)
        if minimum > 5 or maximum > 5 or minimum > maximum:
            raise ValueError(f"{context}: la plage de complexité doit être comprise entre 1 et 5.")

        def providers(field: str) -> Optional[list[str]]:
            value = data.get(field)
            if value is None:
                return None
            if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
                raise ValueError(f"{context}: '{field}' doit être une liste de chaînes non vides.")
            return value

        allowed, excluded = providers("allowed_providers"), providers("excluded_providers")
        if allowed and excluded and {item.lower() for item in allowed} & {item.lower() for item in excluded}:
            raise ValueError(f"{context}: un fournisseur ne peut être à la fois autorisé et exclu.")
        min_context = data.get("min_context_window")
        if min_context is not None:
            min_context = _int(min_context, "min_context_window", context, 1)
        force_model = data.get("force_model")
        if force_model is not None and (not isinstance(force_model, str) or not force_model):
            raise ValueError(f"{context}: 'force_model' doit être une chaîne non vide.")
        mode = data.get("mode")
        if mode is not None and mode not in {"primary", "subagent", "all"}:
            raise ValueError(f"{context}: 'mode' doit être 'primary', 'subagent' ou 'all'.")
        max_budget = data.get("max_monthly_budget")
        if max_budget is not None:
            max_budget = _number(max_budget, "max_monthly_budget", context)
        sort_strategy = data.get("sort_strategy", "lowest_cost")
        valid_strategies = {"lowest_cost", "max_performance", "max_context", "balanced"}
        if not isinstance(sort_strategy, str) or sort_strategy not in valid_strategies:
            valid_list = ", ".join(sorted(valid_strategies))
            raise ValueError(f"{context}: 'sort_strategy' doit être l'un de : {valid_list}.")
        prefer_free = _bool(data.get("prefer_free", False), "prefer_free", context)
        allow_free = _bool(data.get("allow_free", True), "allow_free", context)
        if not allow_free and prefer_free:
            raise ValueError(f"{context}: 'prefer_free' ne peut pas être vrai si 'allow_free' est faux.")
        requires_vision = _bool(data.get("requires_vision", False), "requires_vision", context)
        requires_reasoning = _bool(data.get("requires_reasoning", False), "requires_reasoning", context)
        prefer_tier1 = _bool(data.get("prefer_tier1", True), "prefer_tier1", context)
        return cls(
            name=name,
            description=description,
            min_complexity=minimum,
            max_complexity=maximum,
            requires_tools=_bool(_required(data, "requires_tools", context), "requires_tools", context),
            prefer_free=prefer_free,
            min_context_window=min_context,
            allowed_providers=allowed,
            excluded_providers=excluded,
            force_model=force_model,
            mode=mode,
            estimated_tokens_input=_int(data.get("estimated_tokens_input", 0), "estimated_tokens_input", context),
            estimated_tokens_output=_int(data.get("estimated_tokens_output", 0), "estimated_tokens_output", context),
            max_monthly_budget=max_budget,
            sort_strategy=sort_strategy,
            allow_free=allow_free,
            requires_vision=requires_vision,
            requires_reasoning=requires_reasoning,
            prefer_tier1=prefer_tier1,
        )


@dataclass(frozen=True)
class SelectionResult:
    """Résultat détaillé de l'attribution d'un modèle à un agent."""

    agent_name: str
    model: Optional[Model]
    is_fallback: bool
    candidates: list[Model]
    reason: str


def common_constraint_violations(model: Model, agent_req: AgentRequirement) -> list[str]:
    """Liste les contraintes transversales non respectées par un modèle."""
    violations: list[str] = []
    if agent_req.requires_tools and not model.supports_tools:
        violations.append("support des outils")
    if agent_req.requires_vision and not model.supports_vision:
        violations.append("support de la vision")
    if agent_req.requires_reasoning and not model.supports_reasoning:
        violations.append("modèle de raisonnement requis")
    if agent_req.min_context_window is not None and model.context_window < agent_req.min_context_window:
        violations.append("fenêtre de contexte minimale")
    if agent_req.allowed_providers and model.provider.lower() not in {item.lower() for item in agent_req.allowed_providers}:
        violations.append("fournisseur non autorisé")
    if agent_req.excluded_providers and model.provider.lower() in {item.lower() for item in agent_req.excluded_providers}:
        violations.append("fournisseur exclu")
    if not agent_req.allow_free and model.is_free:
        violations.append("modèle gratuit interdit")
    if agent_req.max_monthly_budget is not None:
        _cost_in, _cost_out, total_cost = model.calculate_cost(
            agent_req.estimated_tokens_input,
            agent_req.estimated_tokens_output,
        )
        if total_cost > agent_req.max_monthly_budget:
            violations.append("plafond budgétaire mensuel")
    return violations


def check_common_constraints(model: Model, agent_req: AgentRequirement) -> bool:
    """Vérifie les contraintes transversales d'un agent."""
    return not common_constraint_violations(model, agent_req)


def is_model_compatible(model: Model, agent_req: AgentRequirement) -> bool:
    """Vérifie si un modèle respecte strictement les contraintes d'un agent."""
    return check_common_constraints(model, agent_req) and (
        agent_req.min_complexity <= model.complexity_score <= agent_req.max_complexity
    )


def is_model_fallback_compatible(model: Model, agent_req: AgentRequirement) -> bool:
    """Vérifie si un modèle est éligible à un surclassement."""
    return check_common_constraints(model, agent_req) and model.complexity_score > agent_req.max_complexity


def _parse_requirement(agent_req: AgentRequirement | dict[str, Any]) -> AgentRequirement:
    return agent_req if isinstance(agent_req, AgentRequirement) else AgentRequirement.from_dict(agent_req)


def _parse_models(models: Sequence[Model | dict[str, Any]]) -> list[Model]:
    return [model if isinstance(model, Model) else Model.from_dict(model) for model in models]


def rank_models_for_agent(agent_req: AgentRequirement | dict[str, Any], models: Sequence[Model | dict[str, Any]], allow_fallback: bool = False) -> list[Model]:
    """Classe les modèles compatibles, puis les surclassements si demandé selon sort_strategy."""
    req, parsed_models = _parse_requirement(agent_req), _parse_models(models)
    exact = [model for model in parsed_models if is_model_compatible(model, req)]

    def key(model: Model, fallback: bool = False) -> tuple[Any, ...]:
        free_penalty = 0 if req.prefer_free and model.is_free else int(req.prefer_free)
        # Priorité aux fournisseurs reconnus de référence (Tier 1) pour éviter les modèles de niche instables
        is_tier1 = model.provider.lower() in TIER1_PROVIDERS or model.provider.lower().lstrip("~") in TIER1_PROVIDERS
        tier1_penalty = 0 if (not req.prefer_tier1 or is_tier1) else 1
        strategy = req.sort_strategy

        if strategy == "max_performance":
            # 1. Pénalité gratuit si prefer_free
            # 2. Préférence Tier 1
            # 3. Performance/complexité maximale d'abord (-complexity_score)
            # 4. Coût le plus bas
            # 5. Fenêtre de contexte la plus large
            # 6. Bris d'égalité déterministe sur l'id
            return (free_penalty, tier1_penalty, -model.complexity_score, model.total_cost_per_m, -model.context_window, model.id)

        if strategy == "max_context":
            # 1. Pénalité gratuit si prefer_free
            # 2. Préférence Tier 1
            # 3. Fenêtre de contexte la plus grande d'abord
            # 4. Coût le plus bas
            # 5. Complexité la plus proche (si fallback) ou la plus haute
            # 6. Bris d'égalité déterministe sur l'id
            comp = model.complexity_score - req.max_complexity if fallback else -model.complexity_score
            return (free_penalty, tier1_penalty, -model.context_window, model.total_cost_per_m, comp, model.id)

        if strategy == "balanced":
            # Compromis valeur/coût :
            # Ratio utilité/coût. Plus le score est élevé, plus le ratio est bon -> donc trier par négatif du score.
            # Coût total lissé avec epsilon (0.05) pour éviter la division par 0 pour les modèles gratuits
            cost_smoothed = model.total_cost_per_m + 0.05
            # Score brut pondéré : complexité + bonus contexte (100k = +1pt)
            context_bonus = min(model.context_window / 100_000, 5.0)
            score = (model.complexity_score * 2.0 + context_bonus) / cost_smoothed
            comp = model.complexity_score - req.max_complexity if fallback else -model.complexity_score
            return (free_penalty, tier1_penalty, -score, model.total_cost_per_m, comp, model.id)

        # Par défaut : "lowest_cost"
        # 1. Pénalité gratuit si prefer_free
        # 2. Coût total le plus bas (garantie économique primordiale)
        # 3. Préférence Tier 1 (en cas de coût équivalent)
        # 4. Complexité la plus proche en fallback, ou la plus haute en exact
        # 5. Fenêtre de contexte la plus large
        # 6. Bris d'égalité déterministe sur l'id
        complexity = model.complexity_score - req.max_complexity if fallback else -model.complexity_score
        return (free_penalty, model.total_cost_per_m, tier1_penalty, complexity, -model.context_window, model.id)

    if exact:
        return sorted(exact, key=key)
    if not allow_fallback:
        return []
    fallback = [model for model in parsed_models if is_model_fallback_compatible(model, req)]
    return sorted(fallback, key=lambda model: key(model, fallback=True))


def resolve_model_for_agent(agent_req: AgentRequirement | dict[str, Any], models: Sequence[Model | dict[str, Any]], allow_fallback: bool = True) -> SelectionResult:
    """Attribue le meilleur modèle, avec override manuel documenté."""
    req, parsed_models = _parse_requirement(agent_req), _parse_models(models)
    if req.force_model:
        matching = next((model for model in parsed_models if model.id == req.force_model), None)
        if matching:
            violations = common_constraint_violations(matching, req)
            if not req.min_complexity <= matching.complexity_score <= req.max_complexity:
                violations.insert(0, "plage de complexité")
            warning = f" Contraintes contournées : {', '.join(violations)}." if violations else ""
            return SelectionResult(req.name, matching, False, [matching], f"Modèle imposé manuellement ({req.force_model}).{warning}")
        return SelectionResult(req.name, None, False, [], f"Modèle imposé '{req.force_model}' introuvable dans le catalogue.")
    exact = rank_models_for_agent(req, parsed_models)
    strategy_suffix = f" (stratégie: {req.sort_strategy})" if req.sort_strategy != "lowest_cost" else ""
    if exact:
        return SelectionResult(req.name, exact[0], False, exact, f"Correspondance exacte avec les exigences{strategy_suffix}.")
    if allow_fallback:
        fallback = rank_models_for_agent(req, parsed_models, allow_fallback=True)
        if fallback:
            chosen = fallback[0]
            return SelectionResult(req.name, chosen, True, fallback, f"Surclassement automatique (fallback) : aucun modèle dans la plage [{req.min_complexity}-{req.max_complexity}], modèle de complexité {chosen.complexity_score} sélectionné{strategy_suffix}.")
    return SelectionResult(req.name, None, False, [], "Aucun modèle compatible trouvé respectant les contraintes.")


def select_model_for_agent(agent_req: AgentRequirement | dict[str, Any], models: Sequence[Model | dict[str, Any]], allow_fallback: bool = True) -> Optional[Model]:
    """Sélectionne le meilleur modèle pour un agent donné."""
    return resolve_model_for_agent(agent_req, models, allow_fallback).model
