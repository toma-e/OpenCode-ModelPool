"""Module de routage d'exécution des modèles LLM.

Permet de découpler le modèle de référence (notations, capacités, context_window)
du canal d'exécution effectif (Ollama local, API directe, ou proxy OpenRouter)
selon l'ordre de priorité défini par l'utilisateur et les clés disponibles.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Set, Tuple

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


@dataclass(frozen=True)
class ExecutionTarget:
    """Cible d'exécution concrète pour un modèle."""

    channel_provider: str          # ex: "ollama", "mistralai", "groq", "openrouter"
    formatted_model_id: str        # ex: "ollama/qwen2.5-coder:7b", "mistral/mistral-large-latest", "openrouter/openai/gpt-4o"
    effective_cost_input_per_m: float
    effective_cost_output_per_m: float
    is_local: bool = False
    description_label: str = ""    # ex: "Ollama Local (0$)", "Mistral Direct API", "OpenRouter Gateway"


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


def resolve_model_execution_target(
    reference_model: Model,
    provider_priority: Sequence[str],
    credentials: Dict[str, ProviderCredentials],
    ollama_models: Optional[Sequence[Model]] = None,
) -> ExecutionTarget:
    """Détermine le meilleur canal d'exécution pour un modèle sélectionné.

    Parcourt l'ordre de priorité :
    1. Si le provider est Ollama et qu'un modèle local équivalent existe -> exécution locale gratuite.
    2. Si le provider est direct (Mistral, Groq, Google, Anthropic, Cerebras) et que la clé est dispo
       et que le modèle correspond au catalogue direct -> exécution directe.
    3. Si le provider est OpenRouter et que la clé OpenRouter est dispo (ou modèle free) -> exécution OpenRouter.
    """
    base_target = normalize_model_basename(reference_model.id)
    ref_provider = reference_model.provider.lower().lstrip("~")

    for provider in provider_priority:
        prov_key = provider.lower()
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
                    )

        # Cas 2 : Fournisseurs directs
        if prov_key in {"mistralai", "mistral"} and is_avail:
            if ref_provider in {"mistralai", "mistral"} or "mistral" in base_target or "codestral" in base_target:
                direct_id = reference_model.id.split("/")[-1] if "/" in reference_model.id else reference_model.id
                return ExecutionTarget(
                    channel_provider="mistralai",
                    formatted_model_id=f"mistral/{direct_id}",
                    effective_cost_input_per_m=reference_model.cost_input_per_m,
                    effective_cost_output_per_m=reference_model.cost_output_per_m,
                    is_local=False,
                    description_label="Mistral AI Direct",
                )

        if prov_key == "groq" and is_avail:
            if ref_provider == "groq" or ("llama" in base_target and "70b" in base_target):
                direct_id = reference_model.id.split("/")[-1] if "/" in reference_model.id else reference_model.id
                return ExecutionTarget(
                    channel_provider="groq",
                    formatted_model_id=f"groq/{direct_id}",
                    effective_cost_input_per_m=reference_model.cost_input_per_m,
                    effective_cost_output_per_m=reference_model.cost_output_per_m,
                    is_local=False,
                    description_label="Groq Direct API",
                )

        if prov_key == "google" and is_avail:
            if ref_provider == "google" or "gemini" in base_target:
                direct_id = reference_model.id.split("/")[-1] if "/" in reference_model.id else reference_model.id
                return ExecutionTarget(
                    channel_provider="google",
                    formatted_model_id=f"google/{direct_id}",
                    effective_cost_input_per_m=reference_model.cost_input_per_m,
                    effective_cost_output_per_m=reference_model.cost_output_per_m,
                    is_local=False,
                    description_label="Google AI Studio Direct",
                )

        if prov_key == "anthropic" and is_avail:
            if ref_provider == "anthropic" or "claude" in base_target:
                direct_id = reference_model.id.split("/")[-1] if "/" in reference_model.id else reference_model.id
                return ExecutionTarget(
                    channel_provider="anthropic",
                    formatted_model_id=f"anthropic/{direct_id}",
                    effective_cost_input_per_m=reference_model.cost_input_per_m,
                    effective_cost_output_per_m=reference_model.cost_output_per_m,
                    is_local=False,
                    description_label="Anthropic Direct",
                )

        if prov_key == "cerebras" and is_avail:
            if ref_provider == "cerebras":
                direct_id = reference_model.id.split("/")[-1] if "/" in reference_model.id else reference_model.id
                return ExecutionTarget(
                    channel_provider="cerebras",
                    formatted_model_id=f"cerebras/{direct_id}",
                    effective_cost_input_per_m=reference_model.cost_input_per_m,
                    effective_cost_output_per_m=reference_model.cost_output_per_m,
                    is_local=False,
                    description_label="Cerebras Direct",
                )

        # Cas 3 : OpenRouter (Passerelle universelle)
        if prov_key == "openrouter":
            # Si déjà préfixé par un provider direct reconnu sans / ou avec son propre préfixe
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
