"""Vérification des modèles réellement accessibles avec chaque clé d'API.

Le catalogue de référence (OpenRouter) décrit les modèles (notation, contexte, capacités),
mais il ne dit pas ce qu'une clé donnée peut réellement appeler. Ce module interroge
l'endpoint « liste des modèles » de chaque fournisseur direct avec la clé détectée et
met le résultat en cache dans ``data/provider_access.json``.

Le cache est lié à l'empreinte masquée de la clé : si la clé change, l'accès est
considéré comme non vérifié jusqu'au prochain rafraîchissement.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from src.providers.detector import ProviderCredentials, get_provider_api_key
from src.selector import Model

ACCESS_CACHE_VERSION = 1

STATUS_OK = "ok"
STATUS_EMPTY = "empty"   # requête aboutie mais aucun modèle (clé invalide, droits insuffisants...)
STATUS_ERROR = "error"   # exception inattendue lors de l'interrogation


@dataclass(frozen=True)
class ProviderAccess:
    """Résultat de la vérification d'accès d'une clé auprès d'un fournisseur direct."""

    provider: str
    masked_key: Optional[str]
    status: str
    model_ids: Tuple[str, ...] = field(default_factory=tuple)
    checked_at: Optional[str] = None
    error: Optional[str] = None


def _strip_provider_prefix(model_id: str) -> str:
    return model_id.split("/", 1)[1] if "/" in model_id else model_id


def probe_provider_access(
    credentials: Mapping[str, ProviderCredentials],
    project_dir: Optional[Path] = None,
    fetchers: Optional[Mapping[str, Callable[..., List[Model]]]] = None,
    key_resolver: Callable[..., Optional[str]] = get_provider_api_key,
) -> Dict[str, ProviderAccess]:
    """Interroge chaque fournisseur direct disposant d'une clé et liste ses modèles accessibles."""
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
        except Exception as error:  # noqa: BLE001 - un connecteur défaillant ne doit pas bloquer les autres
            results[provider] = ProviderAccess(provider, cred.masked_key, STATUS_ERROR, (), now, str(error))
            continue
        ids = tuple(sorted({_strip_provider_prefix(m.id) for m in models}))
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
) -> Tuple[Dict[str, frozenset[str]], List[str]]:
    """Croise le cache avec les clés actuelles.

    Returns:
        (accès vérifiés {fournisseur: ids de modèles}, diagnostics lisibles).
        Un fournisseur absent du dictionnaire n'a pas d'accès vérifié : son canal direct
        ne sera pas utilisé par le routeur.
    """
    verified: Dict[str, frozenset[str]] = {}
    diagnostics: List[str] = []
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
        verified[provider] = frozenset(entry.model_ids)
    return verified, diagnostics
