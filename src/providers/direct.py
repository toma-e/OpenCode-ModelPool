"""Connecteurs vers les catalogues d'API directes (Mistral, Groq, Google, Anthropic, Cerebras).

Permet de requêter les endpoints de modèles officiels avec leurs clés API respectives
et de normaliser les capacités et tarifications au format standardisé OpenCode-ModelPool.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from src.fetcher import estimate_complexity_score
from src.selector import Model, is_non_llm_model

# Tables de tarification de référence par million de tokens (prompt / completion en $)
# Utilisées car plusieurs API directes (ex: Anthropic, Groq, Google) ne fournissent pas
# leurs prix en temps réel dans leur endpoint GET /models.
KNOWN_MODEL_PRICING: Dict[str, tuple[float, float]] = {
    # Mistral AI
    "mistral-large-latest": (2.0, 6.0),
    "mistral-small-latest": (0.2, 0.6),
    "codestral-latest": (0.3, 0.9),
    "ministral-8b-latest": (0.1, 0.1),
    "ministral-3b-latest": (0.04, 0.04),
    "open-mistral-nemo": (0.15, 0.15),
    "open-codestral-mamba": (0.15, 0.15),
    "pixtral-12b-2409": (0.15, 0.15),
    # Groq (prix inférence ultra-rapide)
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "llama-3.1-8b-instant": (0.05, 0.08),
    "llama3-70b-8192": (0.59, 0.79),
    "llama3-8b-8192": (0.05, 0.08),
    "mixtral-8x7b-32768": (0.24, 0.24),
    "gemma2-9b-it": (0.20, 0.20),
    "deepseek-r1-distill-llama-70b": (0.59, 0.79),
    # Google AI Studio / Gemini
    "gemini-2.5-pro": (1.25, 5.0),
    "gemini-2.5-flash": (0.075, 0.30),
    "gemini-2.5-flash-lite": (0.0375, 0.15),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-3-flash-preview": (0.50, 1.00),
    "gemini-1.5-pro": (1.25, 5.0),
    "gemini-1.5-flash": (0.075, 0.30),
    # Anthropic
    "claude-3-7-sonnet-20250219": (3.0, 15.0),
    "claude-3-5-sonnet-latest": (3.0, 15.0),
    "claude-3-5-sonnet-20241022": (3.0, 15.0),
    "claude-3-5-haiku-latest": (0.80, 4.0),
    "claude-3-5-haiku-20241022": (0.80, 4.0),
    "claude-3-opus-latest": (15.0, 75.0),
    "claude-3-opus-20240229": (15.0, 75.0),
    # Cerebras
    "llama3.1-8b": (0.10, 0.10),
    "llama-3.3-70b": (0.60, 0.60),
    "llama3.1-70b": (0.60, 0.60),
    "llama3.3-70b": (0.60, 0.60),
}


def _http_get_json(
    url: str,
    headers: Dict[str, str],
    timeout: float = 5.0,
) -> Optional[dict[str, Any]]:
    """Exécute une requête HTTP GET sécurisée avec la bibliothèque standard."""
    # Cloudflare (Groq, Cerebras) rejette le User-Agent par défaut de urllib (erreur 1010 -> 403)
    headers = {"User-Agent": "OpenCode-ModelPool/1.0", **headers}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read()
            data = json.loads(content.decode("utf-8"))
            return data if isinstance(data, dict) else None
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def fetch_mistral_models(api_key: Optional[str] = None) -> List[Model]:
    """Récupère les modèles depuis l'API directe de Mistral AI."""
    key = api_key or os.environ.get("MISTRAL_API_KEY")
    if not key:
        return []

    url = "https://api.mistral.ai/v1/models"
    data = _http_get_json(url, {"Authorization": f"Bearer {key}", "Accept": "application/json"})
    if not data or not isinstance(data.get("data"), list):
        return []

    models: List[Model] = []
    for item in data["data"]:
        raw_id = item.get("id")
        if not raw_id or not isinstance(raw_id, str):
            continue
        if is_non_llm_model(raw_id) or is_non_llm_model(f"mistral/{raw_id}"):
            continue

        model_id = f"mistral/{raw_id}"
        pricing = KNOWN_MODEL_PRICING.get(raw_id, (0.5, 1.5))
        ctx = item.get("max_context_length") or 32768
        if not isinstance(ctx, int) or ctx < 1:
            ctx = 32768

        complexity = estimate_complexity_score(raw_id, pricing[0])
        supports_tools = any(k in raw_id.lower() for k in ["mistral-large", "mistral-small", "codestral", "nemo"])
        supports_vision = "pixtral" in raw_id.lower()
        supports_reasoning = "r1" in raw_id.lower()

        models.append(
            Model(
                id=model_id,
                provider="mistralai",
                tier="pay_as_you_go",
                cost_input_per_m=pricing[0],
                cost_output_per_m=pricing[1],
                context_window=ctx,
                supports_tools=supports_tools,
                complexity_score=complexity,
                supports_vision=supports_vision,
                supports_reasoning=supports_reasoning,
            )
        )
    return models


def fetch_groq_models(api_key: Optional[str] = None) -> List[Model]:
    """Récupère les modèles depuis l'API Groq (OpenAI-compatible)."""
    key = api_key or os.environ.get("GROQ_API_KEY")
    if not key:
        return []

    url = "https://api.groq.com/openai/v1/models"
    data = _http_get_json(url, {"Authorization": f"Bearer {key}", "Accept": "application/json"})
    if not data or not isinstance(data.get("data"), list):
        return []

    models: List[Model] = []
    for item in data["data"]:
        raw_id = item.get("id")
        if not raw_id or not isinstance(raw_id, str):
            continue
        if is_non_llm_model(raw_id) or is_non_llm_model(f"groq/{raw_id}"):
            continue

        model_id = f"groq/{raw_id}"
        pricing = KNOWN_MODEL_PRICING.get(raw_id, (0.2, 0.4))
        ctx = item.get("context_window") or 8192
        if not isinstance(ctx, int) or ctx < 1:
            ctx = 8192

        complexity = estimate_complexity_score(raw_id, pricing[0])
        supports_tools = any(k in raw_id.lower() for k in ["llama", "mixtral", "gemma"])
        supports_vision = "vision" in raw_id.lower()
        supports_reasoning = any(k in raw_id.lower() for k in ["deepseek-r1", "reasoner"])

        models.append(
            Model(
                id=model_id,
                provider="groq",
                tier="pay_as_you_go",
                cost_input_per_m=pricing[0],
                cost_output_per_m=pricing[1],
                context_window=ctx,
                supports_tools=supports_tools,
                complexity_score=complexity,
                supports_vision=supports_vision,
                supports_reasoning=supports_reasoning,
            )
        )
    return models


def fetch_google_models(api_key: Optional[str] = None) -> List[Model]:
    """Récupère les modèles depuis Google AI Studio (v1beta/models)."""
    key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        return []

    base_url = "https://generativelanguage.googleapis.com/v1beta/models"
    items: List[dict[str, Any]] = []
    page_token: Optional[str] = None
    headers = {"x-goog-api-key": key, "Accept": "application/json"}
    for _ in range(20):  # garde-fou contre une pagination infinie
        url = f"{base_url}?pageSize=1000"
        if page_token:
            url += f"&pageToken={page_token}"
        data = _http_get_json(url, headers)
        if not data or not isinstance(data.get("models"), list):
            break
        items.extend(item for item in data["models"] if isinstance(item, dict))
        page_token = data.get("nextPageToken")
        if not page_token:
            break

    models: List[Model] = []
    for item in items:
        name = item.get("name")  # ex: "models/gemini-2.5-flash"
        if not name or not isinstance(name, str):
            continue
        raw_id = name.replace("models/", "")
        if is_non_llm_model(raw_id) or is_non_llm_model(f"google/{raw_id}"):
            continue
        # Ne conserver que les modèles appelables en génération de texte (chat/agents)
        methods = item.get("supportedGenerationMethods")
        if isinstance(methods, list) and "generateContent" not in methods:
            continue

        model_id = f"google/{raw_id}"
        pricing = KNOWN_MODEL_PRICING.get(raw_id, (0.1, 0.4))
        ctx = item.get("inputTokenLimit") or 32768
        if not isinstance(ctx, int) or ctx < 1:
            ctx = 32768

        complexity = estimate_complexity_score(raw_id, pricing[0])
        supports_tools = True
        supports_vision = True
        supports_reasoning = any(k in raw_id.lower() for k in ["thinking", "2.5-pro", "2.0-flash-thinking"])

        models.append(
            Model(
                id=model_id,
                provider="google",
                tier="pay_as_you_go",
                cost_input_per_m=pricing[0],
                cost_output_per_m=pricing[1],
                context_window=ctx,
                supports_tools=supports_tools,
                complexity_score=complexity,
                supports_vision=supports_vision,
                supports_reasoning=supports_reasoning,
            )
        )
    return models


def fetch_anthropic_models(api_key: Optional[str] = None) -> List[Model]:
    """Récupère les modèles depuis l'API directe Anthropic (/v1/models)."""
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return []

    url = "https://api.anthropic.com/v1/models"
    headers = {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "Accept": "application/json",
    }
    data = _http_get_json(url, headers)
    if not data or not isinstance(data.get("data"), list):
        return []

    models: List[Model] = []
    for item in data["data"]:
        raw_id = item.get("id")
        if not raw_id or not isinstance(raw_id, str):
            continue
        if is_non_llm_model(raw_id) or is_non_llm_model(f"anthropic/{raw_id}"):
            continue

        model_id = f"anthropic/{raw_id}"
        pricing = KNOWN_MODEL_PRICING.get(raw_id, (3.0, 15.0))
        complexity = estimate_complexity_score(raw_id, pricing[0])

        models.append(
            Model(
                id=model_id,
                provider="anthropic",
                tier="pay_as_you_go",
                cost_input_per_m=pricing[0],
                cost_output_per_m=pricing[1],
                context_window=200000,
                supports_tools=True,
                complexity_score=complexity,
                supports_vision=True,
                supports_reasoning="thinking" in raw_id.lower() or "3-7" in raw_id.lower(),
            )
        )
    return models


def fetch_cerebras_models(api_key: Optional[str] = None) -> List[Model]:
    """Récupère les modèles depuis l'API Cerebras (/v1/models)."""
    key = api_key or os.environ.get("CEREBRAS_API_KEY")
    if not key:
        return []

    url = "https://api.cerebras.ai/v1/models"
    data = _http_get_json(url, {"Authorization": f"Bearer {key}", "Accept": "application/json"})
    if not data or not isinstance(data.get("data"), list):
        return []

    models: List[Model] = []
    for item in data["data"]:
        raw_id = item.get("id")
        if not raw_id or not isinstance(raw_id, str):
            continue
        if is_non_llm_model(raw_id) or is_non_llm_model(f"cerebras/{raw_id}"):
            continue

        model_id = f"cerebras/{raw_id}"
        pricing = KNOWN_MODEL_PRICING.get(raw_id, (0.2, 0.4))
        complexity = estimate_complexity_score(raw_id, pricing[0])

        models.append(
            Model(
                id=model_id,
                provider="cerebras",
                tier="pay_as_you_go",
                cost_input_per_m=pricing[0],
                cost_output_per_m=pricing[1],
                context_window=8192,
                supports_tools=True,
                complexity_score=complexity,
                supports_vision=False,
                supports_reasoning=False,
            )
        )
    return models


# Registre des connecteurs directs par identifiant de fournisseur (clé de PROVIDER_ENV_VARS)
DIRECT_FETCHERS = {
    "mistralai": fetch_mistral_models,
    "groq": fetch_groq_models,
    "google": fetch_google_models,
    "anthropic": fetch_anthropic_models,
    "cerebras": fetch_cerebras_models,
}
