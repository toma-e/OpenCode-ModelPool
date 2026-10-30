"""Module pur de diagnostics et de contrôle de fraîcheur du catalogue.

Génère les avertissements et diagnostics d'intégrité pour l'ensemble du parc d'agents,
l'état des clés d'API et la fraîcheur temporelle du catalogue de modèles,
sans effet de bord ni I/O.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence

from src.providers.detector import ProviderCredentials
from src.selector import SelectionResult


def check_catalogue_staleness(
    updated_at_iso: Optional[str],
    max_days: int = 14,
    reference_dt: Optional[datetime] = None,
) -> tuple[bool, Optional[int]]:
    """Vérifie si le catalogue est périmé par rapport à une date de référence (défaut : now UTC).

    Args:
        updated_at_iso: Date ISO-8601 de dernière mise à jour du catalogue.
        max_days: Nombre maximal de jours de validité (défaut : 14).
        reference_dt: Date de référence pour les tests (défaut : datetime.now).

    Returns:
        Tuple (est_périmé: bool, jours_écoulés: Optional[int]).
    """
    if not updated_at_iso or not isinstance(updated_at_iso, str):
        return True, None

    try:
        updated_dt = datetime.fromisoformat(updated_at_iso.replace("Z", "+00:00"))
        ref_dt = reference_dt or (datetime.now(timezone.utc) if updated_dt.tzinfo else datetime.now())
        if updated_dt.tzinfo and not ref_dt.tzinfo:
            ref_dt = ref_dt.replace(tzinfo=timezone.utc)
        elif not updated_dt.tzinfo and ref_dt.tzinfo:
            updated_dt = updated_dt.replace(tzinfo=timezone.utc)

        days_old = (ref_dt - updated_dt).days
        return (days_old > max_days), max(0, days_old)
    except (ValueError, TypeError):
        return True, None


def build_fleet_diagnostics(
    models: Sequence[Any],
    agents: Sequence[Any],
    results: Sequence[SelectionResult],
    catalogue_updated_at: Optional[str] = None,
    credentials: Optional[Mapping[str, ProviderCredentials]] = None,
    verified_access_summary: Optional[Mapping[str, Mapping[str, Any]]] = None,
    max_stale_days: int = 14,
) -> list[str]:
    """Construit la liste ordonnée des alertes et diagnostics pour le parc.

    Contrôles :
    1. État des clés détectées dont les modèles accessibles ne sont pas encore vérifiés.
    2. Modèles ou agents absents de la configuration.
    3. Fraîcheur temporelle du catalogue de modèles.
    4. Agents restés sans modèle compatible attribué.
    """
    diagnostics: list[str] = []

    # 1. Vérification des accès directs non vérifiés
    if credentials:
        access_sum = verified_access_summary or {}
        for prov_name, cred in credentials.items():
            if prov_name in {"ollama", "openrouter"}:
                continue
            if cred.is_available:
                sum_info = access_sum.get(prov_name)
                is_verified = sum_info.get("verified", False) if sum_info else False
                if not is_verified:
                    diagnostics.append(
                        f"Clé {prov_name} détectée mais modèles accessibles non vérifiés : "
                        "lancez 'python3 main.py --refresh-access' (ou --sync)."
                    )

    # 2. Intégrité des données du catalogue et des agents
    if not models:
        diagnostics.append("Le catalogue de modèles est vide.")
    if not agents:
        diagnostics.append("Aucun agent n'est déclaré dans la configuration.")

    # 3. Contrôle de fraîcheur temporelle
    if catalogue_updated_at is None:
        diagnostics.append("La date de mise à jour du catalogue est absente.")
    else:
        is_stale, days_old = check_catalogue_staleness(catalogue_updated_at, max_days=max_stale_days)
        if is_stale and days_old is not None:
            updated_prefix = catalogue_updated_at[:10] if len(catalogue_updated_at) >= 10 else catalogue_updated_at
            diagnostics.append(
                f"Le catalogue date de plus de {days_old} jours ({updated_prefix}). "
                "Pensez à exécuter 'python3 main.py --sync'."
            )

    # 4. Agents non attribués
    unassigned = [res.agent_name for res in results if res.model is None]
    if unassigned:
        diagnostics.append("Agents sans modèle : " + ", ".join(unassigned) + ".")

    return diagnostics
