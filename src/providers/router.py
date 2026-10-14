"""Module de routage d'exécution des modèles LLM.

Permet de découpler le modèle de référence (notations, capacités, context_window)
du canal d'exécution effectif (Ollama local, API directe, ou proxy OpenRouter)
selon l'ordre de priorité défini par l'utilisateur et les clés disponibles.

Lorsqu'une table d'accès vérifié est fournie (``direct_access``), un canal direct
n'est retenu que si le modèle figure réellement dans la liste renvoyée par l'API
du fournisseur pour la clé détectée.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Collection, Dict, Mapping, Optional, Sequence

from src.providers.detector import ProviderCredentials
from src.selector import Model

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
    clean = re.sub(r"-(instruct|it|chat|preview|latest|free)$", "", clean)
    clean = re.sub(r"-\d{8}$", "", clean)  # ex: -20241022
    clean = re.sub(r"-\d+-\d+$", "", clean)  # ex: -4-0
    # Harmonisation qwen-2.5 -> qwen2.5
    clean = clean.replace("qwen-2.5", "qwen2.5").replace("qwen-3", "qwen3")
    return clean


def match_direct_model_id(reference_id: str, available_ids: Collection[str]) -> Optional[str]:
    """Retrouve l'identifiant natif d'un modèle de référence dans la liste réelle d'une clé.

    1. Correspondance exacte (insensible à la casse), avec ou sans variante OpenRouter
       (ex: 'google/gemma-4-26b-a4b-it:free' -> 'gemma-4-26b-a4b-it').
    2. Correspondance sur le nom canonique (``normalize_model_basename``).

    Returns:
        L'identifiant tel qu'attendu par l'API du fournisseur, ou None si absent.
    """
    if not available_ids:
        return None
    raw = reference_id.split("/", 1)[1] if "/" in reference_id else reference_id
    by_lower = {mid.lower(): mid for mid in available_ids}
    for candidate in (raw, raw.split(":", 1)[0]):
        found = by_lower.get(candidate.lower())
        if found:
            return found

    target = normalize_model_basename(raw.split(":", 1)[0])
    for mid in sorted(available_ids):
        if normalize_model_basename(mid) == target:
            return mid
    return None


def resolve_model_execution_target(
    reference_model: Model,
    provider_priority: Sequence[str],
    credentials: Mapping[str, ProviderCredentials],
    ollama_models: Optional[Sequence[Model]] = None,
    direct_access: Optional[Mapping[str, Collection[str]]] = None,
) -> ExecutionTarget:
    """Détermine le meilleur canal d'exécution pour un modèle sélectionné.

    Parcourt l'ordre de priorité :
    1. Ollama : si un modèle local équivalent est installé -> exécution locale gratuite.
    2. Fournisseurs directs (Mistral, Groq, Google, Anthropic, Cerebras) si la clé est dispo :
       - avec ``direct_access`` : uniquement si le modèle figure dans la liste réelle de la clé ;
       - sans ``direct_access`` (accès inconnu) : heuristique sur le nom du modèle.
    3. OpenRouter : passerelle universelle pour le reste du catalogue de référence.
    """
    base_target = normalize_model_basename(reference_model.id)
    ref_provider = reference_model.provider.lower().lstrip("~")

    for provider in provider_priority:
        prov_key = PROVIDER_ALIASES.get(provider.lower(), provider.lower())
        cred = credentials.get(prov_key)
        is_avail = cred.is_available if cred else False

        # Cas 1 : Ollama local
        if prov_key == "ollama" and is_avail and ollama_models:
            for om in ollama_models:
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
                    )

        # Cas 2 : Fournisseurs directs
        channel = DIRECT_CHANNELS.get(prov_key)
        if channel is not None and is_avail:
            native_id: Optional[str] = None
            verified = False
            if direct_access is not None:
                native_id = match_direct_model_id(reference_model.id, direct_access.get(prov_key, ()))
                verified = native_id is not None
            elif channel.heuristic(ref_provider, base_target):
                raw = reference_model.id.split("/", 1)[1] if "/" in reference_model.id else reference_model.id
                native_id = raw
            if native_id:
                return ExecutionTarget(
                    channel_provider=prov_key,
                    formatted_model_id=f"{channel.opencode_prefix}/{native_id}",
                    effective_cost_input_per_m=reference_model.cost_input_per_m,
                    effective_cost_output_per_m=reference_model.cost_output_per_m,
                    is_local=False,
                    description_label=channel.label,
                    access_verified=verified,
                )

        # Cas 3 : OpenRouter (Passerelle universelle)
        if prov_key == "openrouter":
            openrouter_id = reference_model.id
            if not openrouter_id.startswith("openrouter/"):
                openrouter_id = f"openrouter/{openrouter_id}"
            return ExecutionTarget(
                channel_provider="openrouter",
                formatted_model_id=openrouter_id,
                effective_cost_input_per_m=reference_model.cost_input_per_m,
                effective_cost_output_per_m=reference_model.cost_output_per_m,
                is_local=False,
                description_label="OpenRouter Proxy",
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
        is_local=reference_model.is_free,
        description_label="Standard",
    )
