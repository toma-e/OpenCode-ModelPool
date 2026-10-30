"""Tests unitaires du module pur src/diagnostics.py."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from src.diagnostics import build_fleet_diagnostics, check_catalogue_staleness
from src.providers.detector import ProviderCredentials
from src.selector import SelectionResult


class TestDiagnostics(unittest.TestCase):
    """Vérifie le calcul déterministe des diagnostics et de la fraîcheur."""

    def test_catalogue_staleness_none_or_invalid(self) -> None:
        is_stale, days = check_catalogue_staleness(None)
        self.assertTrue(is_stale)
        self.assertIsNone(days)

        is_stale, days = check_catalogue_staleness("invalid-date")
        self.assertTrue(is_stale)
        self.assertIsNone(days)

    def test_catalogue_staleness_calculation(self) -> None:
        now = datetime.now(timezone.utc)
        recent_iso = (now - timedelta(days=5)).isoformat()
        is_stale, days = check_catalogue_staleness(recent_iso, max_days=14, reference_dt=now)
        self.assertFalse(is_stale)
        self.assertEqual(days, 5)

        old_iso = (now - timedelta(days=20)).isoformat()
        is_stale, days = check_catalogue_staleness(old_iso, max_days=14, reference_dt=now)
        self.assertTrue(is_stale)
        self.assertEqual(days, 20)

    def test_build_fleet_diagnostics_empty(self) -> None:
        diag = build_fleet_diagnostics(
            models=[],
            agents=[],
            results=[],
            catalogue_updated_at=None,
        )
        self.assertIn("Le catalogue de modèles est vide.", diag)
        self.assertIn("Aucun agent n'est déclaré dans la configuration.", diag)
        self.assertIn("La date de mise à jour du catalogue est absente.", diag)

    def test_build_fleet_diagnostics_unverified_credentials(self) -> None:
        creds = {
            "google": ProviderCredentials(
                provider="google",
                is_available=True,
                source="env:GOOGLE_API_KEY",
                masked_key="AQ...xyz",
            ),
            "openrouter": ProviderCredentials(
                provider="openrouter",
                is_available=True,
                source="env",
            ),
        }
        diag = build_fleet_diagnostics(
            models=[{"id": "m1"}],
            agents=[{"name": "a1"}],
            results=[],
            catalogue_updated_at=datetime.now(timezone.utc).isoformat(),
            credentials=creds,
            verified_access_summary={"google": {"verified": False}},
        )
        self.assertTrue(any("Clé google détectée mais modèles accessibles non vérifiés" in d for d in diag))
        # openrouter ne doit pas générer d'alerte de vérification directe
        self.assertFalse(any("openrouter" in d for d in diag))

    def test_build_fleet_diagnostics_unassigned_agents(self) -> None:
        res = [
            SelectionResult("agent1", None, False, [], "Aucun modèle"),
            SelectionResult("agent2", None, False, [], "Aucun modèle"),
        ]
        diag = build_fleet_diagnostics(
            models=[{"id": "m1"}],
            agents=[{"name": "a1"}],
            results=res,
            catalogue_updated_at=datetime.now(timezone.utc).isoformat(),
        )
        self.assertTrue(any("Agents sans modèle : agent1, agent2." in d for d in diag))


if __name__ == "__main__":
    unittest.main()
