"""Connecteur vers l'API locale Ollama.

Permet de récupérer les modèles téléchargés localement via GET http://localhost:11434/api/tags
et de les transformer en instances Model avec coût nul et zéro latence réseau externe.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any, List, Optional

from src.fetcher import estimate_complexity_score
from src.selector import Model, is_non_llm_model

DEFAULT_OLLAMA_URL = "http://localhost:11434"


def fetch_ollama_tags(
    base_url: str = DEFAULT_OLLAMA_URL,
    timeout: float = 2.0,
) -> List[dict[str, Any]]:
    """Interroge l'endpoint /api/tags d'Ollama et renvoie la liste brute des modèles."""
    endpoint = f"{base_url.rstrip('/')}/api/tags"
    req = urllib.request.Request(
        endpoint,
        headers={"User-Agent": "OpenCode-ModelPool/1.0", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, dict) and isinstance(data.get("models"), list):
                return [m for m in data["models"] if isinstance(m, dict)]
            return []
    except (urllib.error.URLError, TimeoutError, OSError):
        return []


def parse_ollama_model(raw: dict[str, Any]) -> Optional[Model]:
    """Convertit une entrée modèle brute d'Ollama en instance Model standardisée."""
    name = raw.get("name") or raw.get("model")
    if not name or not isinstance(name, str):
        return None

    # Normalisation du model_id au format ollama/<nom>
    clean_name = name.strip()
    model_id = f"ollama/{clean_name}" if not clean_name.startswith("ollama/") else clean_name
    if is_non_llm_model(clean_name) or is_non_llm_model(model_id):
        return None
    name_lower = clean_name.lower()

    # Détection de la taille et complexité
    complexity = estimate_complexity_score(clean_name, 0.0)

    # Détection de la fenêtre de contexte
    details = raw.get("details", {}) if isinstance(raw.get("details"), dict) else {}
    capabilities = raw.get("capabilities", []) if isinstance(raw.get("capabilities"), list) else []

    context_window = 32768
    if isinstance(details.get("context_length"), int) and details["context_length"] > 0:
        context_window = details["context_length"]
    elif any(k in name_lower for k in ["qwen2.5", "qwen3", "llama3.1", "llama3.2", "llama3.3", "mistral-large"]):
        context_window = 131072
    elif any(k in name_lower for k in ["deepseek-r1", "phi-4"]):
        context_window = 65536

    # Détection des outils (function calling / tool use)
    tools_capable_families = (
        "llama3.1", "llama3.2", "llama3.3", "qwen2.5", "qwen3",
        "mistral", "mixtral", "codestral", "command-r", "firefunction", "hermes"
    )
    supports_tools = "tools" in capabilities or any(kw in name_lower for kw in tools_capable_families)

    # Détection de la vision
    vision_capable_families = ("llava", "vision", "bakllava", "llama3.2-vision", "qwen2-vl", "minicpm-v")
    supports_vision = "vision" in capabilities or any(kw in name_lower for kw in vision_capable_families)

    # Détection du raisonnement
    reasoning_families = ("r1", "deepseek-r1", "qwq", "thinking", "reasoner")
    supports_reasoning = "thinking" in capabilities or any(
        re.search(rf"(?:^|[-_/:])({re.escape(kw)})(?:$|[-_/:])", name_lower)
        for kw in reasoning_families
    )

    return Model(
        id=model_id,
        provider="ollama",
        tier="free_tier",
        cost_input_per_m=0.0,
        cost_output_per_m=0.0,
        context_window=context_window,
        supports_tools=supports_tools,
        complexity_score=complexity,
        supports_vision=supports_vision,
        supports_reasoning=supports_reasoning,
    )


def get_ollama_models(
    base_url: str = DEFAULT_OLLAMA_URL,
    timeout: float = 2.0,
) -> List[Model]:
    """Récupère l'ensemble des modèles locaux Ollama disponibles."""
    raw_models = fetch_ollama_tags(base_url=base_url, timeout=timeout)
    models: List[Model] = []
    for raw in raw_models:
        m = parse_ollama_model(raw)
        if m:
            models.append(m)
    return models
