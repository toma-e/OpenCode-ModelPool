"""Sélection pure et validation des modèles LLM pour les agents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence


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
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < minimum:
        raise ValueError(f"{context}: '{field}' doit être un nombre supérieur ou égal à {minimum}.")
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
        return cls(
            id=model_id,
            provider=provider,
            tier=tier,
            cost_input_per_m=_number(_required(data, "cost_input_per_m", context), "cost_input_per_m", context),
            cost_output_per_m=_number(_required(data, "cost_output_per_m", context), "cost_output_per_m", context),
            context_window=_int(_required(data, "context_window", context), "context_window", context, 1),
            supports_tools=_bool(_required(data, "supports_tools", context), "supports_tools", context),
            complexity_score=complexity,
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
        if mode is not None and mode not in {"primary", "subagent"}:
            raise ValueError(f"{context}: 'mode' doit être 'primary' ou 'subagent'.")
        max_budget = data.get("max_monthly_budget")
        if max_budget is not None:
            max_budget = _number(max_budget, "max_monthly_budget", context)
        return cls(
            name=name,
            description=description,
            min_complexity=minimum,
            max_complexity=maximum,
            requires_tools=_bool(_required(data, "requires_tools", context), "requires_tools", context),
            prefer_free=_bool(data.get("prefer_free", False), "prefer_free", context),
            min_context_window=min_context,
            allowed_providers=allowed,
            excluded_providers=excluded,
            force_model=force_model,
            mode=mode,
            estimated_tokens_input=_int(data.get("estimated_tokens_input", 0), "estimated_tokens_input", context),
            estimated_tokens_output=_int(data.get("estimated_tokens_output", 0), "estimated_tokens_output", context),
            max_monthly_budget=max_budget,
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
    if agent_req.min_context_window is not None and model.context_window < agent_req.min_context_window:
        violations.append("fenêtre de contexte minimale")
    if agent_req.allowed_providers and model.provider.lower() not in {item.lower() for item in agent_req.allowed_providers}:
        violations.append("fournisseur non autorisé")
    if agent_req.excluded_providers and model.provider.lower() in {item.lower() for item in agent_req.excluded_providers}:
        violations.append("fournisseur exclu")
    if agent_req.max_monthly_budget is not None:
        cost = (
            agent_req.estimated_tokens_input / 1_000_000 * model.cost_input_per_m
            + agent_req.estimated_tokens_output / 1_000_000 * model.cost_output_per_m
        )
        if cost > agent_req.max_monthly_budget:
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
    """Classe les modèles compatibles, puis les surclassements si demandé."""
    req, parsed_models = _parse_requirement(agent_req), _parse_models(models)
    exact = [model for model in parsed_models if is_model_compatible(model, req)]

    def key(model: Model, fallback: bool = False) -> tuple[int, float, int]:
        free_penalty = 0 if req.prefer_free and model.is_free else int(req.prefer_free)
        complexity = model.complexity_score - req.max_complexity if fallback else -model.complexity_score
        return free_penalty, model.total_cost_per_m, complexity

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
    if exact:
        return SelectionResult(req.name, exact[0], False, exact, "Correspondance exacte avec les exigences.")
    if allow_fallback:
        fallback = rank_models_for_agent(req, parsed_models, allow_fallback=True)
        if fallback:
            chosen = fallback[0]
            return SelectionResult(req.name, chosen, True, fallback, f"Surclassement automatique (fallback) : aucun modèle dans la plage [{req.min_complexity}-{req.max_complexity}], modèle de complexité {chosen.complexity_score} sélectionné pour sa rentabilité.")
    return SelectionResult(req.name, None, False, [], "Aucun modèle compatible trouvé respectant les contraintes.")


def select_model_for_agent(agent_req: AgentRequirement | dict[str, Any], models: Sequence[Model | dict[str, Any]], allow_fallback: bool = True) -> Optional[Model]:
    """Sélectionne le meilleur modèle pour un agent donné."""
    return resolve_model_for_agent(agent_req, models, allow_fallback).model
