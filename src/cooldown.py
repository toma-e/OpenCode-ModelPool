"""Gestion de la quarantaine temporaire (Circuit-Breaker / Cooldown) des modèles et canaux en erreur.

Lorsqu'un modèle ou un fournisseur rencontre une limite d'utilisation (HTTP 429 Rate Limit),
un quota épuisé (RPD / mensuel), une insuffisance de crédits (HTTP 402), une erreur d'accès
(HTTP 401/403) ou une indisponibilité serveur (HTTP 502/503/504), ce module permet :
1. De classifier automatiquement la nature de l'erreur et d'attribuer une durée de quarantaine (TTL).
2. De vérifier de manière pure si un modèle ou un canal d'exécution est actuellement en quarantaine.
3. De persister atomiquement le registre des quarantaines dans ``data/model_cooldowns.json``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from src.providers.router import PROVIDER_ALIASES, normalize_model_basename

COOLDOWN_SCHEMA_VERSION = 1

REASON_RATE_LIMIT = "rate_limit"
REASON_QUOTA_EXCEEDED = "quota_exceeded"
REASON_INSUFFICIENT_CREDITS = "insufficient_credits"
REASON_SERVICE_UNAVAILABLE = "service_unavailable"
REASON_AUTH_ERROR = "auth_error"
REASON_OTHER = "other"

DEFAULT_COOLDOWN_SECONDS: Dict[str, int] = {
    REASON_RATE_LIMIT: 900,             # 15 minutes (saturation RPM/TPM temporaire)
    REASON_SERVICE_UNAVAILABLE: 1800,   # 30 minutes (erreur 502/503/504 ou timeout)
    REASON_OTHER: 3600,                 # 1 heure
    REASON_QUOTA_EXCEEDED: 43200,       # 12 heures (quota journalier RPD ou mensuel)
    REASON_INSUFFICIENT_CREDITS: 86400, # 24 heures (HTTP 402 solde épuisé)
    REASON_AUTH_ERROR: 86400,           # 24 heures (HTTP 401/403 clé ou modèle non autorisé)
}

ERROR_REASON_LABELS: Dict[str, str] = {
    REASON_RATE_LIMIT: "Limite de débit (HTTP 429 / RPM)",
    REASON_QUOTA_EXCEEDED: "Quota d'utilisation épuisé (RPD / mensuel)",
    REASON_INSUFFICIENT_CREDITS: "Crédits insuffisants (HTTP 402)",
    REASON_SERVICE_UNAVAILABLE: "Service indisponible ou surchargé (5xx / timeout)",
    REASON_AUTH_ERROR: "Erreur d'authentification ou d'autorisation (401/403)",
    REASON_OTHER: "Autre erreur d'exécution",
}

VALID_ERROR_REASONS = frozenset(DEFAULT_COOLDOWN_SECONDS.keys())


def classify_error_reason(
    status_code: Optional[int] = None,
    error_message: str = "",
) -> str:
    """Déduit le code de motif d'erreur normalisé à partir du statut HTTP et du message.

    Distingue notamment un simple rate-limit par minute (``rate_limit``) d'un épuisement
    de quota journalier/mensuel (``quota_exceeded``) ou d'un défaut de crédits (``insufficient_credits``).
    """
    msg = (error_message or "").lower()

    # Détection par mots-clés spécifiques prioritaires
    if any(k in msg for k in ("insufficient_quota", "billing", "insufficient credits", "payment required", "credit balance", "out of credits")):
        return REASON_INSUFFICIENT_CREDITS

    if any(k in msg for k in ("daily limit", "quota exceeded", "monthly limit", "free-models-per-day", "rpd", "resource_exhausted", "usage limit")):
        return REASON_QUOTA_EXCEEDED

    if status_code == 402:
        return REASON_INSUFFICIENT_CREDITS

    if status_code in (401, 403):
        return REASON_AUTH_ERROR

    if status_code == 429 or any(k in msg for k in ("rate limit", "rate_limit", "too many requests", "429", "rpm", "tpm", "throttl")):
        return REASON_RATE_LIMIT

    if (status_code is not None and status_code >= 500) or any(
        k in msg for k in (
            "overloaded",
            "service unavailable",
            "bad gateway",
            "gateway timeout",
            "timeout",
            "idle timeout",
            "upstream idle timeout",
            "stream error",
            "connection reset",
            "502",
            "503",
            "504",
            "connection refused",
        )
    ):
        return REASON_SERVICE_UNAVAILABLE

    if any(k in msg for k in ("unauthorized", "forbidden", "invalid api key", "authentication")):
        return REASON_AUTH_ERROR

    return REASON_OTHER


def _parse_iso_utc(value: str) -> Optional[datetime]:
    """Parse une date ISO-8601 et la normalise en UTC."""
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


@dataclass(frozen=True)
class CooldownEntry:
    """Entrée immuable de mise en quarantaine d'un modèle ou d'un fournisseur."""

    target_id: str
    reason: str
    reported_at: str
    expires_at: str
    error_detail: Optional[str] = None

    def is_active(self, now: Optional[datetime] = None) -> bool:
        """Vérifie si la quarantaine est toujours active à l'instant donné."""
        ref = now if now is not None else datetime.now(timezone.utc)
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=timezone.utc)
        exp = _parse_iso_utc(self.expires_at)
        if exp is None:
            return False
        return ref < exp

    def remaining_seconds(self, now: Optional[datetime] = None) -> int:
        """Retourne le nombre de secondes restantes avant la fin de la quarantaine (0 si expirée)."""
        ref = now if now is not None else datetime.now(timezone.utc)
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=timezone.utc)
        exp = _parse_iso_utc(self.expires_at)
        if exp is None or ref >= exp:
            return 0
        return max(0, int((exp - ref).total_seconds()))

    @property
    def reason_label(self) -> str:
        """Libellé lisible du motif de quarantaine."""
        return ERROR_REASON_LABELS.get(self.reason, ERROR_REASON_LABELS[REASON_OTHER])

    def to_dict(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        """Sérialise l'entrée pour le stockage JSON ou l'API HTTP."""
        payload: Dict[str, Any] = {
            "target_id": self.target_id,
            "reason": self.reason,
            "reason_label": self.reason_label,
            "reported_at": self.reported_at,
            "expires_at": self.expires_at,
            "remaining_seconds": self.remaining_seconds(now=now),
        }
        if self.error_detail:
            payload["error_detail"] = self.error_detail
        return payload

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CooldownEntry:
        """Reconstruit une entrée depuis un dictionnaire JSON."""
        target_id = str(data.get("target_id") or "").strip()
        if not target_id:
            raise ValueError("CooldownEntry: 'target_id' obligatoire.")
        raw_reason = str(data.get("reason") or REASON_OTHER).strip().lower()
        reason = raw_reason if raw_reason in VALID_ERROR_REASONS else REASON_OTHER
        reported_at = str(data.get("reported_at") or "").strip()
        expires_at = str(data.get("expires_at") or "").strip()
        if not _parse_iso_utc(expires_at):
            raise ValueError(f"CooldownEntry: 'expires_at' invalide ({expires_at!r}).")
        detail = data.get("error_detail")
        return cls(
            target_id=target_id,
            reason=reason,
            reported_at=reported_at or datetime.now(timezone.utc).isoformat(),
            expires_at=expires_at,
            error_detail=str(detail) if detail else None,
        )


def create_cooldown_entry(
    target_id: str,
    reason: str = REASON_RATE_LIMIT,
    duration_seconds: Optional[int] = None,
    error_detail: Optional[str] = None,
    now: Optional[datetime] = None,
) -> CooldownEntry:
    """Crée une nouvelle entrée de quarantaine avec calcul automatique de ``expires_at``."""
    clean_target = target_id.strip()
    if not clean_target:
        raise ValueError("L'identifiant de cible à mettre en quarantaine ne peut pas être vide.")
    norm_reason = reason.strip().lower() if reason else REASON_RATE_LIMIT
    if norm_reason not in VALID_ERROR_REASONS:
        norm_reason = classify_error_reason(error_message=reason)

    ttl = duration_seconds if (duration_seconds is not None and duration_seconds > 0) else DEFAULT_COOLDOWN_SECONDS[norm_reason]
    ref = now if now is not None else datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    exp = ref + timedelta(seconds=ttl)
    return CooldownEntry(
        target_id=clean_target,
        reason=norm_reason,
        reported_at=ref.isoformat(),
        expires_at=exp.isoformat(),
        error_detail=error_detail.strip() if error_detail and error_detail.strip() else None,
    )


def _normalize_provider_token(provider: str) -> str:
    p = provider.strip().lower().lstrip("~")
    return PROVIDER_ALIASES.get(p, p)


def is_provider_in_cooldown(
    provider: str,
    active_entries: Sequence[CooldownEntry],
) -> Optional[CooldownEntry]:
    """Vérifie si un fournisseur/canal entier (ex: ``provider:groq``) est en quarantaine."""
    if not provider or not active_entries:
        return None
    norm_prov = _normalize_provider_token(provider)
    for entry in active_entries:
        t = entry.target_id.strip().lower()
        if t.startswith("provider:"):
            entry_prov = _normalize_provider_token(t.split(":", 1)[1])
            if entry_prov == norm_prov:
                return entry
    return None


def _strip_openrouter_prefix(model_id: str) -> str:
    m = model_id.strip().lower()
    if m.startswith("openrouter/"):
        return m[len("openrouter/"):]
    return m


def is_model_in_cooldown(
    model_id: str,
    formatted_target_id: str,
    channel_provider: str,
    active_entries: Sequence[CooldownEntry],
) -> Optional[CooldownEntry]:
    """Vérifie si un modèle ou son canal d'exécution est actuellement en quarantaine.

    Reconnaît les correspondances exactes sur :
    - le fournisseur entier (``provider:<channel_provider>``)
    - l'identifiant catalogue (ex: ``nvidia/nemotron-3-ultra-550b-a55b:free``)
    - l'identifiant formaté OpenCode (ex: ``openrouter/nvidia/nemotron-3-ultra-550b-a55b:free`` ou ``groq/openai/gpt-oss-120b``)
    """
    if not active_entries:
        return None

    prov_entry = is_provider_in_cooldown(channel_provider, active_entries)
    if prov_entry is not None:
        return prov_entry

    m_lower = model_id.strip().lower()
    f_lower = formatted_target_id.strip().lower()
    m_stripped = _strip_openrouter_prefix(m_lower)
    f_stripped = _strip_openrouter_prefix(f_lower)

    candidate_tokens = {m_lower, f_lower, m_stripped, f_stripped}
    candidate_Tokens_non_empty = {t for t in candidate_tokens if t}

    for entry in active_entries:
        target = entry.target_id.strip().lower()
        if target.startswith("provider:"):
            continue
        target_stripped = _strip_openrouter_prefix(target)
        if target in candidate_Tokens_non_empty or target_stripped in {m_stripped, f_stripped}:
            return entry

    return None


def read_cooldowns(path: Path, now: Optional[datetime] = None) -> List[CooldownEntry]:
    """Lit les quarantaines actives depuis le disque en filtrant automatiquement celles expirées."""
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(raw, dict):
        return []
    items = raw.get("cooldowns")
    if not isinstance(items, list):
        return []

    ref = now if now is not None else datetime.now(timezone.utc)
    active: List[CooldownEntry] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            entry = CooldownEntry.from_dict(item)
            if entry.is_active(now=ref):
                active.append(entry)
        except ValueError:
            continue
    return active


def write_cooldowns(path: Path, entries: Sequence[CooldownEntry], now: Optional[datetime] = None) -> None:
    """Écrit de manière atomique les quarantaines actives dans ``data/model_cooldowns.json``."""
    from src.fetcher import write_json_atomic

    ref = now if now is not None else datetime.now(timezone.utc)
    # Conserver uniquement la dernière entrée active par target_id (insensible à la casse)
    by_target: Dict[str, CooldownEntry] = {}
    for entry in entries:
        if entry.is_active(now=ref):
            by_target[entry.target_id.strip().lower()] = entry

    sorted_entries = sorted(by_target.values(), key=lambda e: e.target_id.lower())
    payload = {
        "version": COOLDOWN_SCHEMA_VERSION,
        "updated_at": ref.isoformat(),
        "cooldowns": [e.to_dict(now=ref) for e in sorted_entries],
    }
    write_json_atomic(path, payload)
