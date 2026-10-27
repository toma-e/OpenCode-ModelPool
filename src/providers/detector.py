"""Détection sécurisée des clés d'API et configurations locales de fournisseurs LLM.

Ce module permet de détecter les fournisseurs exploitables via :
1. Les variables d'environnement courantes (*_API_KEY, *_KEY, etc.)
2. Les fichiers d'authentification OpenCode (~/.local/share/opencode/auth.json)
3. Les fichiers .env locaux (lecture non destructive, sans écraser os.environ)
4. L'accessibilité du service local Ollama (http://localhost:11434)

Ne consigne ni n'affiche jamais la clé API brute en clair (sécurité offensive / audit).
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set

# Cartographie standardisée des fournisseurs vers leurs variables d'environnement courantes
PROVIDER_ENV_VARS: Dict[str, List[str]] = {
    "openrouter": ["OPENROUTER_API_KEY", "OPENROUTER_KEY"],
    "mistralai": ["MISTRAL_API_KEY", "MISTRAL_KEY"],
    "groq": ["GROQ_API_KEY"],
    "google": ["GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_AI_API_KEY"],
    "anthropic": ["ANTHROPIC_API_KEY"],
    "cerebras": ["CEREBRAS_API_KEY"],
    "openai": ["OPENAI_API_KEY"],
    "deepseek": ["DEEPSEEK_API_KEY"],
}


@dataclass(frozen=True)
class ProviderCredentials:
    """Informations de disponibilité d'un fournisseur sans divulguer le secret."""

    provider: str
    is_available: bool
    source: str  # "env", "opencode_auth", "dotenv", "local_service", "none"
    masked_key: Optional[str] = None


def mask_key(key: Optional[str]) -> Optional[str]:
    """Masque une clé d'API pour journalisation et diagnostic sécurisés."""
    if not key or not isinstance(key, str):
        return None
    cleaned = key.strip()
    if len(cleaned) <= 8:
        return "****"
    return f"{cleaned[:4]}...{cleaned[-4:]}"


def parse_dotenv_file(dotenv_path: Path) -> Dict[str, str]:
    """Lit un fichier .env simple sans dépendance tierce et sans modifier os.environ."""
    env_vars: Dict[str, str] = {}
    if not dotenv_path.is_file():
        return env_vars
    try:
        content = dotenv_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return env_vars

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        env_vars[key] = val
    return env_vars


def load_opencode_auth_keys(auth_path: Optional[Path] = None) -> Dict[str, str]:
    """Extrait les tokens ou clés configurés dans le fichier auth d'OpenCode."""
    if auth_path is None:
        auth_path = Path.home() / ".local" / "share" / "opencode" / "auth.json"
    if not auth_path.is_file():
        return {}
    try:
        data = json.loads(auth_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        # Normalisation des clés trouvées (ex: {"openrouter": {"key": "..."}, "anthropic": "..."})
        keys: Dict[str, str] = {}
        for prov, val in data.items():
            if isinstance(val, str) and val.strip():
                keys[prov.lower()] = val.strip()
            elif isinstance(val, dict):
                token = val.get("key") or val.get("token") or val.get("apiKey")
                if isinstance(token, str) and token.strip():
                    keys[prov.lower()] = token.strip()
        return keys
    except Exception:
        return {}


def is_ollama_reachable(base_url: str = "http://localhost:11434", timeout: float = 1.0) -> bool:
    """Vérifie rapidement si le service Ollama local est actif."""
    url = f"{base_url.rstrip('/')}/api/tags"
    req = urllib.request.Request(url, headers={"User-Agent": "OpenCode-ModelPool/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _resolve_key(
    provider: str,
    var_names: List[str],
    dotenv_keys: Dict[str, str],
    opencode_keys: Dict[str, str],
) -> tuple[Optional[str], str]:
    """Recherche la clé d'un fournisseur : os.environ > .env projet > auth OpenCode."""
    for var_name in var_names:
        env_val = os.environ.get(var_name)
        if env_val and env_val.strip():
            return env_val.strip(), "env"

    for var_name in var_names:
        dot_val = dotenv_keys.get(var_name)
        if dot_val and dot_val.strip():
            return dot_val.strip(), "dotenv"

    auth_val = opencode_keys.get(provider)
    if not auth_val and provider == "mistralai":
        auth_val = opencode_keys.get("mistral")
    if auth_val:
        return auth_val, "opencode_auth"
    return None, "none"


def get_provider_api_key(
    provider: str,
    project_dir: Optional[Path] = None,
    opencode_auth_path: Optional[Path] = None,
) -> Optional[str]:
    """Renvoie la clé brute d'un fournisseur (usage interne uniquement, jamais sérialisée)."""
    var_names = PROVIDER_ENV_VARS.get(provider)
    if var_names is None:
        return None
    dotenv_keys = parse_dotenv_file(project_dir / ".env") if project_dir is not None else {}
    key, _source = _resolve_key(provider, var_names, dotenv_keys, load_opencode_auth_keys(opencode_auth_path))
    return key


def detect_provider_credentials(
    project_dir: Optional[Path] = None,
    check_ollama: bool = True,
    ollama_base_url: str = "http://localhost:11434",
    opencode_auth_path: Optional[Path] = None,
) -> Dict[str, ProviderCredentials]:
    """Détecte les identifiants disponibles pour l'ensemble des fournisseurs supportés."""
    results: Dict[str, ProviderCredentials] = {}

    # 1. Vérification .env projet
    dotenv_keys: Dict[str, str] = {}
    if project_dir is not None:
        dotenv_keys = parse_dotenv_file(project_dir / ".env")

    # 2. Vérification auth OpenCode
    opencode_keys = load_opencode_auth_keys(opencode_auth_path)

    # 3. Évaluation pour chaque fournisseur d'API (os.environ > .env > auth OpenCode)
    for provider, var_names in PROVIDER_ENV_VARS.items():
        found_key, source = _resolve_key(provider, var_names, dotenv_keys, opencode_keys)
        is_avail = bool(found_key)
        results[provider] = ProviderCredentials(
            provider=provider,
            is_available=is_avail,
            source=source,
            masked_key=mask_key(found_key) if is_avail else None,
        )

    # 4. Évaluation Ollama (service local)
    ollama_ok = is_ollama_reachable(ollama_base_url) if check_ollama else False
    results["ollama"] = ProviderCredentials(
        provider="ollama",
        is_available=ollama_ok,
        source="local_service" if ollama_ok else "none",
        masked_key=None,
    )

    return results


def get_available_provider_names(
    credentials: Optional[Dict[str, ProviderCredentials]] = None,
    allow_unkeyed_openrouter_free: bool = True,
    project_dir: Optional[Path] = None,
    opencode_auth_path: Optional[Path] = None,
) -> Set[str]:
    """Renvoie la liste des identifiants de fournisseurs exploitables."""
    if credentials is None:
        credentials = detect_provider_credentials(
            project_dir=project_dir,
            opencode_auth_path=opencode_auth_path,
            check_ollama=True,
        )

    available = {prov for prov, cred in credentials.items() if cred.is_available}

    # OpenRouter dispose d'un catalogue public et de modèles gratuits accessibles
    if allow_unkeyed_openrouter_free:
        available.add("openrouter")

    return available
