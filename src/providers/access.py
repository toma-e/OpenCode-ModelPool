"""Vérification des modèles réellement accessibles avec chaque clé d'API.

Le catalogue de référence (OpenRouter) décrit les modèles (notation, contexte, capacités),
mais il ne dit pas ce qu'une clé donnée peut réellement appeler. Ce module interroge
l'endpoint « liste des modèles » de chaque fournisseur direct avec la clé détectée et
met le résultat en cache dans ``data/provider_access.json``.

Pour éviter d'attribuer des modèles qui renvoient un 429 (rate limit / quota nul)
ou 401/402/403 dès la première requête, une micro-requête de test (chat completion /
generateContent avec 1 token) est effectuée en parallèle pour chaque modèle découvert.

Le cache est lié à l'empreinte masquée de la clé : si la clé change, l'accès est
considéré comme non vérifié jusqu'au prochain rafraîchissement.
"""

from __future__ import annotations

import concurrent.futures
import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from src.providers.detector import ProviderCredentials, get_provider_api_key
from src.selector import Model

ACCESS_CACHE_VERSION = 1

STATUS_OK = "ok"
STATUS_EMPTY = "empty"   # requête aboutie mais aucun modèle (droits insuffisants...)
STATUS_ERROR = "error"   # exception inattendue lors de l'interrogation
STATUS_AUTH_ERROR = "auth_error"  # clé invalide ou non autorisée (401/403)
STATUS_RATE_LIMIT = "rate_limit"  # débit limité ou quota temporaire (429)

MAX_CACHE_AGE_DAYS = 14

_PROBE_USER_AGENT = "OpenCode-ModelPool/1.0"


@dataclass(frozen=True)
class ProviderAccess:
    """Résultat de la vérification d'accès d'une clé auprès d'un fournisseur direct."""

    provider: str
    masked_key: Optional[str]
    status: str
    model_ids: Tuple[str, ...] = field(default_factory=tuple)
    checked_at: Optional[str] = None
    error: Optional[str] = None


def _strip_provider_prefix(model_id: str, provider: Optional[str] = None) -> str:
    """Retire uniquement le préfixe propre au provider (ex: 'groq/openai/gpt-oss' -> 'openai/gpt-oss')."""
    if not model_id:
        return model_id
    if provider:
        p = provider.lower()
        aliases = {"mistralai": "mistral", "google": "google", "groq": "groq", "cerebras": "cerebras", "anthropic": "anthropic"}
        prefixes = {p, aliases.get(p, p)}
        for prefix in prefixes:
            if model_id.startswith(f"{prefix}/"):
                return model_id[len(prefix) + 1:]
    # Fallback générique si le premier segment est un nom de connecteur connu
    known = {"groq", "mistral", "mistralai", "cerebras", "google", "anthropic", "ollama", "openrouter"}
    if "/" in model_id:
        first, rest = model_id.split("/", 1)
        if first.lower() in known:
            return rest
    return model_id


def test_model_live_availability(
    provider: str,
    raw_model_id: str,
    api_key: str,
    timeout: float = 3.5,
) -> bool:
    """Envoie une micro-requête minimale pour vérifier si le modèle répond 200 OK.

    Élimine d'office les modèles soumis à un 429 (rate limit permanent / quota nul),
    403 (palier non autorisé) ou 404/402.
    """
    clean_id = _strip_provider_prefix(raw_model_id, provider=provider)

    # 1. Fournisseurs OpenAI-compatibles (Mistral, Groq, Cerebras)
    if provider in {"mistralai", "mistral", "groq", "cerebras"}:
        if provider in {"mistralai", "mistral"}:
            url = "https://api.mistral.ai/v1/chat/completions"
        elif provider == "groq":
            url = "https://api.groq.com/openai/v1/chat/completions"
        else:
            url = "https://api.cerebras.ai/v1/chat/completions"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": _PROBE_USER_AGENT,
        }
        payload = json.dumps({
            "model": clean_id,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        }).encode("utf-8")

        req = urllib.request.Request(url, data=payload, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return bool(getattr(resp, "status", None) == 200)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
            return False

    # 2. Google AI Studio (Gemini v1beta)
    if provider == "google":
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{clean_id}:generateContent"
        )
        headers = {
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
            "User-Agent": _PROBE_USER_AGENT,
        }
        payload = json.dumps({
            "contents": [{"parts": [{"text": "ping"}]}],
            "generationConfig": {"maxOutputTokens": 1},
        }).encode("utf-8")

        req = urllib.request.Request(url, data=payload, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return bool(getattr(resp, "status", None) == 200)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
            return False

    # 3. Anthropic
    if provider == "anthropic":
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
            "User-Agent": _PROBE_USER_AGENT,
        }
        payload = json.dumps({
            "model": clean_id,
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "ping"}],
        }).encode("utf-8")

        req = urllib.request.Request(url, data=payload, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return bool(getattr(resp, "status", None) == 200)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
            return False

    # Fournisseur non géré pour la micro-requête : on valide par défaut
    return True


def probe_provider_access(
    credentials: Mapping[str, ProviderCredentials],
    project_dir: Optional[Path] = None,
    fetchers: Optional[Mapping[str, Callable[..., List[Model]]]] = None,
    key_resolver: Callable[..., Optional[str]] = get_provider_api_key,
    verify_live_call: bool = True,
) -> Dict[str, ProviderAccess]:
    """Interroge chaque fournisseur direct et filtre les modèles opérationnels en direct."""
    if fetchers is None:
        from src.providers.direct import DIRECT_FETCHERS

        fetchers = DIRECT_FETCHERS

    now = datetime.now(timezone.utc).isoformat()
    results: Dict[str, ProviderAccess] = {}
    for provider, fetcher in fetchers.items():
        cred = credentials.get(provider)
        if cred is None or not cred.is_available:
            continue
        key = key_resolver(provider, project_dir=project_dir)
        if not key:
            continue
        try:
            models = fetcher(api_key=key)
        except urllib.error.HTTPError as error:
            if error.code in (401, 403):
                err_status = STATUS_AUTH_ERROR
                err_msg = f"Authentification refusée (HTTP {error.code})"
            elif error.code == 429:
                err_status = STATUS_RATE_LIMIT
                err_msg = "Limite de débit / quota temporairement atteint (HTTP 429)"
            elif error.code == 404:
                err_status = STATUS_ERROR
                err_msg = "Endpoint ou ressource introuvable (HTTP 404)"
            elif error.code >= 500:
                err_status = STATUS_ERROR
                err_msg = f"Service fournisseur indisponible (HTTP {error.code})"
            else:
                err_status = STATUS_ERROR
                err_msg = f"Erreur HTTP {error.code}"
            results[provider] = ProviderAccess(provider, cred.masked_key, err_status, (), now, err_msg)
            continue
        except urllib.error.URLError as error:
            results[provider] = ProviderAccess(provider, cred.masked_key, STATUS_ERROR, (), now, f"Erreur réseau : {error.reason}")
            continue
        except TimeoutError:
            results[provider] = ProviderAccess(provider, cred.masked_key, STATUS_ERROR, (), now, "Délai d'attente dépassé (timeout)")
            continue
        except Exception as error:  # noqa: BLE001 - un connecteur défaillant ne doit pas bloquer les autres
            results[provider] = ProviderAccess(provider, cred.masked_key, STATUS_ERROR, (), now, str(error))
            continue

        raw_ids = tuple(sorted({_strip_provider_prefix(m.id, provider=provider) for m in models}))

        # Micro-requête de test en parallèle si demandée pour éliminer 429 / 403
        if verify_live_call and raw_ids:
            verified_ids: List[str] = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                future_to_id = {
                    executor.submit(test_model_live_availability, provider, mid, key): mid
                    for mid in raw_ids
                }
                for future in concurrent.futures.as_completed(future_to_id):
                    mid = future_to_id[future]
                    try:
                        if future.result():
                            verified_ids.append(mid)
                    except Exception:  # noqa: BLE001
                        pass
            ids = tuple(sorted(verified_ids))
        else:
            ids = raw_ids

        status = STATUS_OK if ids else STATUS_EMPTY
        results[provider] = ProviderAccess(provider, cred.masked_key, status, ids, now)
    return results


def write_provider_access(path: Path, access: Mapping[str, ProviderAccess]) -> None:
    """Enregistre le cache d'accès (sans aucune clé en clair)."""
    from src.fetcher import write_json_atomic

    payload = {
        "version": ACCESS_CACHE_VERSION,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "providers": {
            name: {
                "masked_key": item.masked_key,
                "status": item.status,
                "checked_at": item.checked_at,
                "error": item.error,
                "model_count": len(item.model_ids),
                "models": list(item.model_ids),
            }
            for name, item in sorted(access.items())
        },
    }
    write_json_atomic(path, payload)


def read_provider_access(path: Path) -> Dict[str, ProviderAccess]:
    """Lit le cache d'accès ; renvoie un dictionnaire vide s'il est absent ou corrompu."""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    providers = data.get("providers") if isinstance(data, dict) else None
    if not isinstance(providers, dict):
        return {}
    results: Dict[str, ProviderAccess] = {}
    for name, entry in providers.items():
        if not isinstance(entry, dict):
            continue
        models = entry.get("models")
        ids = tuple(m for m in models if isinstance(m, str)) if isinstance(models, list) else ()
        results[name] = ProviderAccess(
            provider=name,
            masked_key=entry.get("masked_key"),
            status=str(entry.get("status") or STATUS_ERROR),
            model_ids=ids,
            checked_at=entry.get("checked_at"),
            error=entry.get("error"),
        )
    return results


def resolve_verified_access(
    cached: Mapping[str, ProviderAccess],
    credentials: Mapping[str, ProviderCredentials],
    direct_providers: Sequence[str],
    max_cache_age_days: int = MAX_CACHE_AGE_DAYS,
    strict_freshness: bool = False,
) -> Tuple[Dict[str, frozenset[str]], List[str]]:
    """Croise le cache avec les clés actuelles.

    Returns:
        (accès vérifiés {fournisseur: ids de modèles}, diagnostics lisibles).
        Un fournisseur absent du dictionnaire n'a pas d'accès vérifié : son canal direct
        ne sera pas utilisé par le routeur.
    """
    verified: Dict[str, frozenset[str]] = {}
    diagnostics: List[str] = []
    now_dt = datetime.now(timezone.utc)
    for provider in direct_providers:
        cred = credentials.get(provider)
        if cred is None or not cred.is_available:
            continue
        entry = cached.get(provider)
        if entry is None:
            diagnostics.append(
                f"Clé {provider} détectée mais modèles accessibles non vérifiés : "
                "lancez 'python3 main.py --refresh-access' (ou --sync)."
            )
            continue
        if entry.masked_key != cred.masked_key:
            diagnostics.append(
                f"La clé {provider} a changé depuis la dernière vérification : "
                "lancez 'python3 main.py --refresh-access'."
            )
            continue
        if entry.status != STATUS_OK:
            detail = f" ({entry.error})" if entry.error else ""
            diagnostics.append(
                f"Aucun modèle accessible avec la clé {provider}{detail} : canal direct désactivé."
            )
            continue

        # Vérification de la fraîcheur du cache (MP-212)
        if entry.checked_at:
            try:
                checked_dt = datetime.fromisoformat(entry.checked_at.replace("Z", "+00:00"))
                age_days = (now_dt - checked_dt).days
                if age_days > max_cache_age_days:
                    diagnostics.append(
                        f"Vérification d'accès pour {provider} périmée ({age_days} jours > {max_cache_age_days}j) : "
                        "lancez 'python3 main.py --refresh-access'."
                    )
                    if strict_freshness:
                        continue
            except (ValueError, TypeError):
                pass

        verified[provider] = frozenset(entry.model_ids)
    return verified, diagnostics
