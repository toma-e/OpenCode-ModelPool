"""Sélection pure et validation des modèles LLM pour les agents."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Collection, Mapping, Optional, Sequence


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

# Expresssions régulières pré-compilées pour la détection rapide des modèles non-LLM
_RE_AUDIO_VOICE: re.Pattern[str] = re.compile(
    r"(?:^|[-_/:])(?:suno|udio|audio|voice|tts|xtts)(?:$|[-_/:])"
)
_RE_CHIRP_SPEECH: re.Pattern[str] = re.compile(
    r"(?:^|[-_/:])(?:chirp|speech(?:t\d*)?)(?:$|[-_/:0-9])"
)
_RE_EMBED_RERANK: re.Pattern[str] = re.compile(
    r"(?:^|[-_/:])(?:embed|embedding|embeddings|bge|gte|e5|rerank|reranker|aqa|voyage|voyageai)(?:$|[-_/:])"
)
_RE_IMAGE_GEN_MODELS: re.Pattern[str] = re.compile(
    r"(?:^|[-_/:])(?:flux|sora|veo|runway)(?:$|[-_/:0-9])"
)
_RE_IMAGE_GEN_PATTERNS: re.Pattern[str] = re.compile(
    r"[-_/:]image(?:$|[-_/:0-9])"
)
_RE_MODERATION: re.Pattern[str] = re.compile(
    r"(?:^|[-_/:])moderation(?:$|[-_/:])"
)
_RE_ROBOTICS: re.Pattern[str] = re.compile(
    r"(?:^|[-_/:])(?:openvla|octo|rt-[12]|pi0)(?:$|[-_/:])"
)


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
        valid_strategies = {"lowest_cost", "max_performance", "max_context", "balanced", "prefer_provider"}
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


def is_non_llm_model(
    model_id: str,
    architecture: Optional[dict[str, Any]] = None,
    output_modalities: Optional[list[str]] = None,
) -> bool:
    """Détecte si un modèle n'est pas un LLM génératif de texte/code (audio, musique, embed, image, etc.)."""
    if output_modalities:
        norm = [str(m).lower().strip() for m in output_modalities]
        if not any(t in norm for t in ("text", "code")):
            return True

    if isinstance(architecture, dict):
        arch_out = architecture.get("output_modalities")
        if isinstance(arch_out, list) and len(arch_out) > 0:
            norm_arch = [str(m).lower().strip() for m in arch_out]
            if not any(t in norm_arch for t in ("text", "code")):
                return True
        modality = str(architecture.get("modality", "")).lower().strip()
        if "->" in modality:
            _, _, outp = modality.partition("->")
            outp = outp.strip()
            if outp and not any(t in outp for t in ("text", "code")):
                return True

    m_id = model_id.lower()

    # Audio / Musique / Parole / Transcription
    if any(k in m_id for k in ("lyria", "musiclm", "whisper", "transcription", "seamless")):
        return True
    if _RE_AUDIO_VOICE.search(m_id):
        return True
    if _RE_CHIRP_SPEECH.search(m_id):
        return True

    # Embeddings & Reranking
    if _RE_EMBED_RERANK.search(m_id):
        return True
    if "minilm" in m_id or "nomic-embed" in m_id or "mistral-embed" in m_id:
        return True

    # Génération d'images / Vidéo
    if any(k in m_id for k in ("imagen", "dall-e", "dalle", "midjourney", "stable-diffusion", "sdxl", "cogvideo", "hunyuan-video")):
        return True
    if _RE_IMAGE_GEN_MODELS.search(m_id):
        return True
    if _RE_IMAGE_GEN_PATTERNS.search(m_id) and not ("image-to-text" in m_id or "image2text" in m_id):
        return True

    # Modération pure
    if _RE_MODERATION.search(m_id):
        return True

    # Robotique / Embodied AI
    if _RE_ROBOTICS.search(m_id):
        return True

    return False


def common_constraint_violations(model: Model, agent_req: AgentRequirement) -> list[str]:
    """Liste les contraintes transversales non respectées par un modèle."""
    violations: list[str] = []
    if is_non_llm_model(model.id):
        violations.append("modèle non-génératif (non-LLM)")
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


def _is_model_excluded(model_id: str, excluded_models: Optional[Collection[str]]) -> bool:
    """Vérifie de manière insensible à la casse et au préfixe openrouter/ si un modèle est exclu (ex: quarantaine)."""
    if not excluded_models:
        return False
    norm_set = {m.strip().lower() for m in excluded_models if m}
    m_low = model_id.strip().lower()
    m_stripped = m_low[len("openrouter/"):] if m_low.startswith("openrouter/") else m_low
    return m_low in norm_set or m_stripped in norm_set or f"openrouter/{m_stripped}" in norm_set


def rank_models_for_agent(
    agent_req: AgentRequirement | dict[str, Any],
    models: Sequence[Model | dict[str, Any]],
    allow_fallback: bool = False,
    channel_rank: Optional[Mapping[str, int]] = None,
    channel_costs: Optional[Mapping[str, float]] = None,
    excluded_models: Optional[Collection[str]] = None,
) -> list[Model]:
    """Classe les modèles compatibles, puis les surclassements si demandé selon sort_strategy.

    Stratégies :
    - 'lowest_cost' : coût total prévu le plus bas d'abord (garantie économique primordiale),
      puis départage par rang de canal, Tier 1, complexité, contexte et id.
    - 'prefer_provider' : priorité stricte au rang de canal (ex: crédits gratuits ou API directe
      souhaitée), puis coût et aptitude.
    - 'max_performance' : niveau de complexité/performance d'abord, puis Tier 1, rang de canal et coût.
    - 'balanced' : ratio qualité estimée / coût, puis rang de canal et coût.
    - 'max_context' : fenêtre de contexte maximale, puis rang de canal et coût.
    """
    req, parsed_models = _parse_requirement(agent_req), _parse_models(models)
    if excluded_models:
        parsed_models = [m for m in parsed_models if not _is_model_excluded(m.id, excluded_models)]
    exact = [model for model in parsed_models if is_model_compatible(model, req)]

    def key(model: Model, fallback: bool = False) -> tuple[Any, ...]:
        rank = channel_rank.get(model.id, 10**6) if channel_rank else 0
        effective_cost = channel_costs.get(model.id, model.total_cost_per_m) if channel_costs else model.total_cost_per_m
        free_penalty = 0 if req.prefer_free and (model.is_free or effective_cost == 0.0) else int(req.prefer_free)
        # Priorité aux fournisseurs reconnus de référence (Tier 1) pour éviter les modèles de niche instables
        is_tier1 = model.provider.lower() in TIER1_PROVIDERS or model.provider.lower().lstrip("~") in TIER1_PROVIDERS
        tier1_penalty = 0 if (not req.prefer_tier1 or is_tier1) else 1
        strategy = req.sort_strategy

        if strategy == "prefer_provider":
            # Priorité stricte au canal d'exécution retenu
            comp = model.complexity_score - req.max_complexity if fallback else -model.complexity_score
            return (rank, free_penalty, effective_cost, tier1_penalty, comp, -model.context_window, model.id)

        if strategy == "max_performance":
            return (free_penalty, tier1_penalty, -model.complexity_score, rank, effective_cost, -model.context_window, model.id)

        if strategy == "max_context":
            comp = model.complexity_score - req.max_complexity if fallback else -model.complexity_score
            return (free_penalty, tier1_penalty, -model.context_window, rank, effective_cost, comp, model.id)

        if strategy == "balanced":
            cost_smoothed = effective_cost + 0.05
            context_bonus = min(model.context_window / 100_000, 5.0)
            score = (model.complexity_score * 2.0 + context_bonus) / cost_smoothed
            comp = model.complexity_score - req.max_complexity if fallback else -model.complexity_score
            return (free_penalty, tier1_penalty, -score, rank, effective_cost, comp, model.id)

        # Par défaut : "lowest_cost"
        # 1. Pénalité gratuit si prefer_free
        # 2. Coût total effectif le plus bas (garantie économique primordiale)
        # 3. Rang de canal (départage à coût égal : ex: Ollama local vs OpenRouter gratuit)
        # 4. Préférence Tier 1 (en cas de coût équivalent)
        # 5. Complexité la plus proche en fallback, ou la plus haute en exact
        # 6. Fenêtre de contexte la plus large
        # 7. Bris d'égalité déterministe sur l'id
        complexity = model.complexity_score - req.max_complexity if fallback else -model.complexity_score
        return (free_penalty, effective_cost, rank, tier1_penalty, complexity, -model.context_window, model.id)

    if exact:
        return sorted(exact, key=key)
    if not allow_fallback:
        return []
    fallback = [model for model in parsed_models if is_model_fallback_compatible(model, req)]
    return sorted(fallback, key=lambda model: key(model, fallback=True))


def resolve_model_for_agent(
    agent_req: AgentRequirement | dict[str, Any],
    models: Sequence[Model | dict[str, Any]],
    allow_fallback: bool = True,
    channel_rank: Optional[Mapping[str, int]] = None,
    channel_costs: Optional[Mapping[str, float]] = None,
    excluded_models: Optional[Collection[str]] = None,
) -> SelectionResult:
    """Attribue le meilleur modèle, avec override manuel documenté et repli si modèle en quarantaine."""
    req, parsed_models = _parse_requirement(agent_req), _parse_models(models)
    if req.force_model:
        if _is_model_excluded(req.force_model, excluded_models):
            # Le modèle imposé est en quarantaine suite à une erreur : bascule automatique sur les candidats sains
            exact_alt = rank_models_for_agent(
                req, parsed_models, channel_rank=channel_rank, channel_costs=channel_costs, excluded_models=excluded_models
            )
            if exact_alt:
                chosen = exact_alt[0]
                return SelectionResult(
                    req.name,
                    chosen,
                    True,
                    exact_alt,
                    f"Repli sur erreur : le modèle imposé ({req.force_model}) est en quarantaine temporaire, bascule vers '{chosen.id}'.",
                )
            if allow_fallback:
                fb_alt = rank_models_for_agent(
                    req,
                    parsed_models,
                    allow_fallback=True,
                    channel_rank=channel_rank,
                    channel_costs=channel_costs,
                    excluded_models=excluded_models,
                )
                if fb_alt:
                    chosen = fb_alt[0]
                    return SelectionResult(
                        req.name,
                        chosen,
                        True,
                        fb_alt,
                        f"Repli sur erreur (surclassement) : le modèle imposé ({req.force_model}) est en quarantaine temporaire, bascule vers '{chosen.id}'.",
                    )
            return SelectionResult(
                req.name,
                None,
                False,
                [],
                f"Modèle imposé '{req.force_model}' en quarantaine temporaire et aucun modèle de repli compatible disponible.",
            )
        matching = next((model for model in parsed_models if model.id == req.force_model), None)
        if matching:
            violations = common_constraint_violations(matching, req)
            if not req.min_complexity <= matching.complexity_score <= req.max_complexity:
                violations.insert(0, "plage de complexité")
            warning = f" Contraintes contournées : {', '.join(violations)}." if violations else ""
            # Fournir tout de même les candidats alternatifs sains pour la fallback_chain
            other_candidates = rank_models_for_agent(
                req, parsed_models, allow_fallback=allow_fallback, channel_rank=channel_rank, channel_costs=channel_costs, excluded_models=excluded_models
            )
            all_cands = [matching] + [m for m in other_candidates if m.id != matching.id]
            return SelectionResult(req.name, matching, False, all_cands, f"Modèle imposé manuellement ({req.force_model}).{warning}")
        return SelectionResult(req.name, None, False, [], f"Modèle imposé '{req.force_model}' introuvable dans le catalogue.")
    exact = rank_models_for_agent(
        req, parsed_models, channel_rank=channel_rank, channel_costs=channel_costs, excluded_models=excluded_models
    )
    strategy_suffix = f" (stratégie: {req.sort_strategy})" if req.sort_strategy != "lowest_cost" else ""
    if exact:
        return SelectionResult(req.name, exact[0], False, exact, f"Correspondance exacte avec les exigences{strategy_suffix}.")
    if allow_fallback:
        fallback = rank_models_for_agent(
            req, parsed_models, allow_fallback=True, channel_rank=channel_rank, channel_costs=channel_costs, excluded_models=excluded_models
        )
        if fallback:
            chosen = fallback[0]
            return SelectionResult(req.name, chosen, True, fallback, f"Surclassement automatique (fallback) : aucun modèle dans la plage [{req.min_complexity}-{req.max_complexity}], modèle de complexité {chosen.complexity_score} sélectionné{strategy_suffix}.")
    return SelectionResult(req.name, None, False, [], "Aucun modèle compatible trouvé respectant les contraintes.")


def build_hybrid_fallback_chain(
    primary_formatted_id: str,
    primary_channel: str,
    candidate_targets: Sequence[tuple[str, str]],
    max_length: int = 3,
) -> list[str]:
    """Construit une chaîne de repli hybride ordonnée pour un agent.

    - Passe 1 (Priorité Inter-Canaux) : privilégie d'abord des candidats exécutables sur
      des fournisseurs/canaux distincts du modèle principal (évite les limites de débit globales au fournisseur).
    - Passe 2 (Complément Intra-Canal) : si moins de ``max_length`` modèles ont été retenus en Passe 1,
      complète avec d'autres modèles distincts sur les canaux déjà représentés (ex: autre modèle sur OpenRouter).
    """
    if max_length <= 0 or not primary_formatted_id:
        return []

    seen_channels: set[str] = {primary_channel.lower()} if primary_channel else set()
    seen_ids: set[str] = {primary_formatted_id}
    chain: list[str] = []

    # Passe 1 : Canaux distincts en priorité
    for formatted_id, channel in candidate_targets:
        if not formatted_id or formatted_id in seen_ids:
            continue
        norm_chan = (channel or "").lower()
        if norm_chan in seen_channels:
            continue
        seen_channels.add(norm_chan)
        seen_ids.add(formatted_id)
        chain.append(formatted_id)
        if len(chain) >= max_length:
            return chain

    # Passe 2 : Complément sur les mêmes canaux avec des modèles distincts
    for formatted_id, _channel in candidate_targets:
        if not formatted_id or formatted_id in seen_ids:
            continue
        seen_ids.add(formatted_id)
        chain.append(formatted_id)
        if len(chain) >= max_length:
            return chain

    return chain


def select_model_for_agent(agent_req: AgentRequirement | dict[str, Any], models: Sequence[Model | dict[str, Any]], allow_fallback: bool = True) -> Optional[Model]:
    """Sélectionne le meilleur modèle pour un agent donné."""
    return resolve_model_for_agent(agent_req, models, allow_fallback).model
