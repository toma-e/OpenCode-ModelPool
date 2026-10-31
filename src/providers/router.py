"""Module de routage d'exécution des modèles LLM.

Permet de découpler le modèle de référence (notations, capacités, context_window)
du canal d'exécution effectif (Ollama local, API directe, ou proxy OpenRouter)
selon l'ordre de priorité défini par l'utilisateur et les clés disponibles.

Lorsqu'une table d'accès vérifié est fournie (``direct_access``), un canal direct
n'est retenu que si le modèle figure réellement dans la liste renvoyée par l'API
du fournisseur pour la clé détectée.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Collection, Dict, Mapping, Optional, Sequence, Set

from src.providers.detector import ProviderCredentials
from src.selector import AgentRequirement, Model

DEFAULT_PROVIDER_PRIORITY: list[str] = [
    "ollama",
    "groq",
    "mistralai",
    "google",
    "cerebras",
    "anthropic",
    "openrouter",
]

# Alias acceptés dans l'ordre de priorité saisi par l'utilisateur
PROVIDER_ALIASES: Dict[str, str] = {"mistral": "mistralai", "gemini": "google"}

# Alias de normalisation vers la nomenclature stricte des adaptateurs OpenCode (@ai-sdk/*)
OPENCODE_DIRECT_MODEL_ALIASES: Dict[str, Dict[str, str]] = {
    "mistral": {
        "mistral-large-4-0": "mistral-large-4",
        "mistral-large-4-0-8": "mistral-large-4",
        "mistral-large": "mistral-large-latest",
        "codestral": "codestral-latest",
        "ministral-14b-latest": "ministral-14b-2512",
        "ministral-8b": "ministral-8b-latest",
        "ministral-3b": "ministral-3b-latest",
        "mistral-code-latest": "codestral-latest",
        "mistral-code-fim-latest": "codestral-latest",
    },
    "google": {
        "gemini-flash-latest": "gemini-flash-latest",
        "gemini-pro-latest": "gemini-pro-latest",
    },
    "groq": {
        "llama-3.3-70b": "llama-3.3-70b-versatile",
        "llama-3.1-8b": "llama-3.1-8b-instant",
    },
    "anthropic": {
        "claude-3-5-sonnet": "claude-sonnet-4-5",
        "claude-3-5-haiku": "claude-haiku-4-5",
    },
    "cerebras": {
        "llama-3.3-70b": "gpt-oss-120b",
    },
}

# Catalogue de référence des modèles enregistrés dans OpenCode par adaptateur
OPENCODE_FALLBACK_KNOWN_MODELS: Dict[str, Set[str]] = {
    "mistral": {
        "codestral-2508", "codestral-latest", "deepseek-v4-1-flash-1017",
        "devstral-2512", "devstral-latest", "devstral-medium-latest",
        "glm-5-2", "labs-devstral-small-2512", "labs-leanstral-1-5-1",
        "magistral-medium-latest", "ministral-14b-2512", "ministral-3b-2512",
        "ministral-3b-latest", "ministral-8b-2512", "ministral-8b-latest",
        "mistral-embed", "mistral-large-2512", "mistral-large-4",
        "mistral-large-4-0-8", "mistral-large-latest", "mistral-medium-2505",
        "mistral-medium-2508", "mistral-medium-2604", "mistral-medium-latest",
        "mistral-small-2506", "mistral-small-2603", "mistral-small-latest",
        "open-mistral-nemo", "pixtral-12b", "voxtral-mini-latest",
        "voxtral-mini-tts-latest", "voxtral-small-2507", "voxtral-small-latest",
    },
    "groq": {
        "allam-2-7b", "llama-3.1-8b-instant", "llama-3.3-70b-versatile",
        "openai/gpt-oss-120b", "openai/gpt-oss-20b", "openai/gpt-oss-safeguard-20b",
        "qwen/qwen3.6-27b", "qwen/qwen3.8-27b", "whisper-large-v3",
        "whisper-large-v3-turbo",
    },
    "google": {
        "gemini-2.5-computer-use-preview-10-2025", "gemini-2.5-flash",
        "gemini-2.5-flash-lite", "gemini-2.5-pro", "gemini-3-flash-preview",
        "gemini-3.1-flash-lite", "gemini-3.1-flash-lite-preview",
        "gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.6-flash",
        "gemini-3.7-flash", "gemini-3.8-flash", "gemini-4-argon",
        "gemini-flash-latest", "gemini-flash-lite-latest", "gemini-omni-flash-preview",
        "gemini-pro-latest", "gemma-4-26b-a4b-it", "gemma-4-31b-it",
    },
    "anthropic": {
        "claude-fable-5", "claude-fable-5-1", "claude-haiku-4-5",
        "claude-haiku-4-5-20251001", "claude-haiku-5-5", "claude-opus-4-5",
        "claude-opus-4-5-20251101", "claude-opus-4-6", "claude-opus-4-7",
        "claude-opus-4-8", "claude-opus-5", "claude-opus-5-5",
        "claude-sonnet-4-5", "claude-sonnet-4-5-20250929", "claude-sonnet-4-6",
        "claude-sonnet-5", "claude-sonnet-5-5",
    },
    "cerebras": {
        "gpt-oss-120b", "qwen-3.8-27b",
    },
}


def load_opencode_known_models(cache_path: Optional[Path] = None) -> Dict[str, Set[str]]:
    """Charge les modèles reconnus par les adaptateurs OpenCode depuis le cache local ou le catalogue statique."""
    known: Dict[str, Set[str]] = {k: set(v) for k, v in OPENCODE_FALLBACK_KNOWN_MODELS.items()}
    path = cache_path or (Path.home() / ".cache" / "opencode" / "models.json")
    if path.is_file():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for prov, pdata in data.items():
                    if isinstance(pdata, dict) and "models" in pdata:
                        models = pdata["models"]
                        if isinstance(models, dict):
                            known.setdefault(prov, set()).update(models.keys())
        except (OSError, json.JSONDecodeError):
            pass
    return known


def canonicalize_opencode_model_id(opencode_prefix: str, raw_model_id: str) -> str:
    """Convertit un identifiant d'API directe vers la nomenclature officielle OpenCode."""
    clean_id = raw_model_id.strip()
    if "/" in clean_id and not clean_id.startswith("openai/") and not clean_id.startswith("meta-llama/"):
        prov_candidate, rest = clean_id.split("/", 1)
        if prov_candidate.lower() in ("mistral", "google", "groq", "anthropic", "cerebras"):
            clean_id = rest

    if clean_id.startswith("models/"):
        clean_id = clean_id.replace("models/", "")

    aliases = OPENCODE_DIRECT_MODEL_ALIASES.get(opencode_prefix, {})
    return aliases.get(clean_id, clean_id)


def is_opencode_supported_model(
    opencode_prefix: str,
    model_id: str,
    known_models: Optional[Dict[str, Set[str]]] = None,
) -> bool:
    """Vérifie si un modèle direct est officiellement reconnu par l'adaptateur OpenCode."""
    if opencode_prefix in ("openrouter", "ollama"):
        return True
    if known_models is None:
        known_models = load_opencode_known_models()
    supported = known_models.get(opencode_prefix)
    if supported is None:
        return True
    return model_id in supported


@dataclass(frozen=True)
class ExecutionTarget:
    """Cible d'exécution concrète pour un modèle."""

    channel_provider: str          # ex: "ollama", "mistralai", "groq", "openrouter"
    formatted_model_id: str        # ex: "ollama/qwen2.5-coder:7b", "mistral/mistral-large-latest", "openrouter/openai/gpt-4o"
    effective_cost_input_per_m: float
    effective_cost_output_per_m: float
    is_local: bool = False
    description_label: str = ""    # ex: "Ollama Local (0$)", "Mistral Direct API", "OpenRouter Gateway"
    access_verified: bool = False  # True si le modèle a été trouvé dans la liste réelle de la clé
    native_model_id: str = ""
    pricing_source: str = "openrouter_catalog"
    is_heuristic_match: bool = False
    verification_status: str = "unverified"


@dataclass(frozen=True)
class _DirectChannel:
    opencode_prefix: str
    label: str
    heuristic: Callable[[str, str], bool]  # (ref_provider, base_target) -> compatible ?


DIRECT_CHANNELS: Dict[str, _DirectChannel] = {
    "mistralai": _DirectChannel(
        "mistral",
        "Mistral AI Direct",
        lambda ref, base: ref in {"mistralai", "mistral"} or "mistral" in base or "codestral" in base,
    ),
    "groq": _DirectChannel(
        "groq",
        "Groq Direct API",
        lambda ref, base: ref == "groq" or ("llama" in base and "70b" in base),
    ),
    "google": _DirectChannel(
        "google",
        "Google AI Studio Direct",
        lambda ref, base: ref == "google" or "gemini" in base,
    ),
    "anthropic": _DirectChannel(
        "anthropic",
        "Anthropic Direct",
        lambda ref, base: ref == "anthropic" or "claude" in base,
    ),
    "cerebras": _DirectChannel(
        "cerebras",
        "Cerebras Direct",
        lambda ref, _base: ref == "cerebras",
    ),
}


def normalize_model_basename(model_id: str) -> str:
    """Extrait le nom canonique épuré d'un modèle pour comparaison multi-fournisseurs.

    Exemples:
        'mistralai/mistral-large-4-0' -> 'mistral-large'
        'mistral/mistral-large-latest' -> 'mistral-large'
        'qwen/qwen-2.5-coder-7b-instruct' -> 'qwen2.5-coder-7b'
        'ollama/qwen2.5-coder:7b' -> 'qwen2.5-coder-7b'
        'anthropic/claude-3-5-sonnet-20241022' -> 'claude-3-5-sonnet'
    """
    clean = model_id.lower()
    # Retrait du préfixe provider s'il existe
    if "/" in clean:
        clean = clean.split("/", 1)[1]

    # Remplacement des deux-points et séparateurs de version
    clean = clean.replace(":", "-").replace("_", "-")
    # Retrait des suffixes communs
    clean = re.sub(r"-(instruct|it|chat|preview|latest|free|versatile|instant)$", "", clean)
    clean = re.sub(r"-\d{8}$", "", clean)  # ex: -20241022
    clean = re.sub(r"-\d+-\d+$", "", clean)  # ex: -4-0
    # Harmonisation qwen-2.5 -> qwen2.5
    clean = clean.replace("qwen-2.5", "qwen2.5").replace("qwen-3", "qwen3")
    return clean


def match_direct_model_id(
    reference_id: str,
    available_ids: Collection[str],
    opencode_prefix: Optional[str] = None,
) -> Optional[str]:
    """Retrouve l'identifiant natif d'un modèle de référence dans la liste réelle d'une clé.

    1. Correspondance exacte (insensible à la casse), avec ou sans variante OpenRouter
       (ex: 'google/gemma-4-26b-a4b-it:free' -> 'gemma-4-26b-a4b-it').
    2. Correspondance sur le nom canonique (``normalize_model_basename``),
       en privilégiant systématiquement les identifiants officiels supportés par OpenCode.

    Returns:
        L'identifiant tel qu'attendu par l'API du fournisseur, ou None si absent.
    """
    if not available_ids:
        return None
    raw = reference_id.split("/", 1)[1] if "/" in reference_id else reference_id
    raw_no_variant = raw.split(":", 1)[0]
    by_lower = {mid.lower(): mid for mid in available_ids}

    # 1. Correspondance exacte ou via alias OpenCode
    for candidate in (raw, raw_no_variant):
        found = by_lower.get(candidate.lower())
        if found:
            if opencode_prefix:
                canon = canonicalize_opencode_model_id(opencode_prefix, found)
                if canon.lower() in by_lower:
                    return by_lower[canon.lower()]
                return canon
            return found

    if opencode_prefix:
        canon_raw = canonicalize_opencode_model_id(opencode_prefix, raw_no_variant)
        found_canon = by_lower.get(canon_raw.lower())
        if found_canon:
            return found_canon

    # 2. Correspondance canonique par basename
    target = normalize_model_basename(raw_no_variant)
    matching_candidates: list[str] = []
    for mid in sorted(available_ids):
        if normalize_model_basename(mid) == target:
            matching_candidates.append(mid)

    if not matching_candidates:
        return None

    # Si plusieurs candidats matchent (ex: mistral-large-4 et mistral-large-4-0),
    # prioriser impérativement celui qui est officiellement supporté par OpenCode
    if opencode_prefix:
        for mid in matching_candidates:
            canon = canonicalize_opencode_model_id(opencode_prefix, mid)
            if is_opencode_supported_model(opencode_prefix, canon):
                return canon

    first = matching_candidates[0]
    return canonicalize_opencode_model_id(opencode_prefix, first) if opencode_prefix else first


def resolve_model_execution_target(
    reference_model: Model,
    provider_priority: Sequence[str],
    credentials: Mapping[str, ProviderCredentials],
    ollama_models: Optional[Sequence[Model]] = None,
    direct_access: Optional[Mapping[str, Collection[str]]] = None,
    excluded_targets: Optional[Collection[str]] = None,
    agent_requirement: Optional[AgentRequirement] = None,
) -> ExecutionTarget:
    """Détermine le meilleur canal d'exécution pour un modèle sélectionné.

    Parcourt l'ordre de priorité :
    1. Ollama : si un modèle local équivalent est installé -> exécution locale gratuite.
    2. Fournisseurs directs (Mistral, Groq, Google, Anthropic, Cerebras) si la clé est dispo :
       - avec ``direct_access`` : uniquement si le modèle figure dans la liste réelle de la clé ;
       - sans ``direct_access`` (accès inconnu) : heuristique sur le nom du modèle.
    3. OpenRouter : passerelle universelle pour le reste du catalogue de référence.

    Si ``excluded_targets`` est fourni (quarantaine / cooldown), tout canal (``provider:<nom>``)
    ou identifiant de cible formaté présent dans ``excluded_targets`` est ignoré au profit du canal suivant.
    """
    base_target = normalize_model_basename(reference_model.id)
    ref_provider = reference_model.provider.lower().lstrip("~")
    excluded_norm = {t.strip().lower() for t in excluded_targets if t} if excluded_targets else set()

    for provider in provider_priority:
        prov_key = PROVIDER_ALIASES.get(provider.lower(), provider.lower())
        if f"provider:{prov_key}" in excluded_norm or f"provider:{provider.lower()}" in excluded_norm:
            continue
        cred = credentials.get(prov_key)
        is_avail = cred.is_available if cred else False

        # Cas 1 : Ollama local
        if prov_key == "ollama" and is_avail and ollama_models:
            for om in ollama_models:
                if om.id.lower() in excluded_norm:
                    continue
                om_base = normalize_model_basename(om.id)
                # Correspondance exacte ou partielle forte (ex: qwen2.5-coder-7b et qwen2.5-coder:7b)
                if om_base == base_target or (len(om_base) > 4 and om_base in base_target) or (len(base_target) > 4 and base_target in om_base):
                    return ExecutionTarget(
                        channel_provider="ollama",
                        formatted_model_id=om.id,
                        effective_cost_input_per_m=0.0,
                        effective_cost_output_per_m=0.0,
                        is_local=True,
                        description_label="Ollama Local (0$)",
                        access_verified=True,
                        native_model_id=om.id,
                        pricing_source="local_free",
                        is_heuristic_match=False,
                        verification_status="verified",
                    )

        # Cas 2 : Fournisseurs directs
        channel = DIRECT_CHANNELS.get(prov_key)
        if channel is not None and is_avail:
            # Compatibilité de l'agent :
            # Pour Groq : rejeter si la fenêtre de contexte requise dépasse la limite TPM (8000 tokens)
            # ou si les outils sont obligatoires et non supportés par la variante Groq
            if prov_key == "groq" and agent_requirement is not None:
                min_ctx = agent_requirement.min_context_window or 0
                if min_ctx > 8000 and "llama-3.1-8b" not in base_target:
                    continue
                if agent_requirement.requires_tools and not any(k in base_target for k in ["llama", "mixtral", "gemma"]):
                    continue

            native_id: Optional[str] = None
            verified = False
            if direct_access is not None:
                native_id = match_direct_model_id(
                    reference_model.id,
                    direct_access.get(prov_key, ()),
                    opencode_prefix=channel.opencode_prefix,
                )
                verified = native_id is not None
            elif channel.heuristic(ref_provider, base_target):
                raw = reference_model.id.split("/", 1)[1] if "/" in reference_model.id else reference_model.id
                native_id = canonicalize_opencode_model_id(channel.opencode_prefix, raw)

            if native_id:
                # S'assurer de la canonisation vers la nomenclature OpenCode
                canon_id = canonicalize_opencode_model_id(channel.opencode_prefix, native_id)
                formatted_direct_id = f"{channel.opencode_prefix}/{canon_id}"
                if formatted_direct_id.lower() in excluded_norm:
                    continue
                from src.providers.direct import get_known_model_pricing
                pricing = get_known_model_pricing(canon_id, (0.0, 0.0))
                if pricing != (0.0, 0.0):
                    cost_in, cost_out = pricing
                    pricing_source = "direct_api_pricing"
                elif reference_model.cost_input_per_m > 0 or reference_model.cost_output_per_m > 0:
                    cost_in, cost_out = reference_model.cost_input_per_m, reference_model.cost_output_per_m
                    pricing_source = "reference_model_catalog"
                elif reference_model.is_free:
                    cost_in, cost_out = 0.0, 0.0
                    pricing_source = "free_tier"
                else:
                    cost_in, cost_out = 0.0, 0.0
                    pricing_source = "unknown"
                return ExecutionTarget(
                    channel_provider=prov_key,
                    formatted_model_id=formatted_direct_id,
                    effective_cost_input_per_m=cost_in,
                    effective_cost_output_per_m=cost_out,
                    is_local=False,
                    description_label=channel.label,
                    access_verified=verified,
                    native_model_id=canon_id,
                    pricing_source=pricing_source,
                    is_heuristic_match=not verified,
                    verification_status="verified" if verified else "unverified",
                )

        # Cas 3 : OpenRouter (Passerelle universelle)
        if prov_key == "openrouter":
            openrouter_id = reference_model.id
            if not openrouter_id.startswith("openrouter/"):
                openrouter_id = f"openrouter/{openrouter_id}"
            if openrouter_id.lower() in excluded_norm:
                continue
            is_or_verified = is_avail
            return ExecutionTarget(
                channel_provider="openrouter",
                formatted_model_id=openrouter_id,
                effective_cost_input_per_m=reference_model.cost_input_per_m,
                effective_cost_output_per_m=reference_model.cost_output_per_m,
                is_local=False,
                description_label="OpenRouter Proxy",
                access_verified=False,
                native_model_id=reference_model.id,
                pricing_source="openrouter_catalog",
                is_heuristic_match=False,
                verification_status="verified" if is_or_verified else "unverified",
            )

    # Fallback par défaut si aucune clé ne correspond
    formatted_id = reference_model.id
    if not any(formatted_id.startswith(f"{p}/") for p in ["openrouter", "ollama", "mistral", "groq", "google", "anthropic", "cerebras"]):
        formatted_id = f"openrouter/{formatted_id}"
    return ExecutionTarget(
        channel_provider=ref_provider or "openrouter",
        formatted_model_id=formatted_id,
        effective_cost_input_per_m=reference_model.cost_input_per_m,
        effective_cost_output_per_m=reference_model.cost_output_per_m,
        is_local=False,
        description_label="Standard",
        access_verified=False,
        native_model_id=reference_model.id,
        pricing_source="reference_model_catalog",
        is_heuristic_match=True,
        verification_status="unverified",
    )
