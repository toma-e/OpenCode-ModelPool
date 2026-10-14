"""Tests unitaires pour la vérification des modèles réellement accessibles par clé."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from src.providers.access import (
    STATUS_EMPTY,
    STATUS_ERROR,
    STATUS_OK,
    ProviderAccess,
    probe_provider_access,
    read_provider_access,
    resolve_verified_access,
    write_provider_access,
)
from src.providers.detector import ProviderCredentials
from src.providers.router import (
    DEFAULT_PROVIDER_PRIORITY,
    match_direct_model_id,
    resolve_model_execution_target,
)
from src.selector import Model


class TestProviderAccess(unittest.TestCase):
    def test_match_direct_model_id(self) -> None:
        available = {"gemini-2.5-flash", "gemini-2.5-pro", "gemma-4-26b-a4b-it"}

        # Correspondance exacte sans préfixe
        self.assertEqual(match_direct_model_id("gemini-2.5-flash", available), "gemini-2.5-flash")
        # Avec préfixe google/
        self.assertEqual(match_direct_model_id("google/gemini-2.5-flash", available), "gemini-2.5-flash")
        # Avec suffixe OpenRouter :free
        self.assertEqual(match_direct_model_id("google/gemma-4-26b-a4b-it:free", available), "gemma-4-26b-a4b-it")
        # Modèle non présent dans la liste
        self.assertIsNone(match_direct_model_id("google/lyria-3-clip-preview", available))
        self.assertIsNone(match_direct_model_id("openai/gpt-4o", available))

    def test_probe_provider_access_success(self) -> None:
        creds = {
            "google": ProviderCredentials(provider="google", is_available=True, source="env", masked_key="AQ.A...JqHA"),
        }
        mock_fetcher = MagicMock(return_value=[
            Model("google/gemini-2.5-flash", "google", "pay_as_you_go", 0.075, 0.3, 1000000, True, 4),
            Model("google/gemma-4-26b-a4b-it", "google", "pay_as_you_go", 0.1, 0.4, 32768, True, 3),
        ])

        results = probe_provider_access(
            creds,
            fetchers={"google": mock_fetcher},
            key_resolver=lambda prov, project_dir=None: "fake-key",
        )

        self.assertIn("google", results)
        acc = results["google"]
        self.assertEqual(acc.status, STATUS_OK)
        self.assertEqual(acc.masked_key, "AQ.A...JqHA")
        self.assertIn("gemini-2.5-flash", acc.model_ids)
        self.assertIn("gemma-4-26b-a4b-it", acc.model_ids)

    def test_probe_provider_access_handles_failure(self) -> None:
        creds = {
            "google": ProviderCredentials(provider="google", is_available=True, source="env", masked_key="AQ.A...JqHA"),
        }
        mock_fetcher = MagicMock(side_effect=RuntimeError("quota exceeded"))

        results = probe_provider_access(
            creds,
            fetchers={"google": mock_fetcher},
            key_resolver=lambda prov, project_dir=None: "fake-key",
        )

        self.assertIn("google", results)
        self.assertEqual(results["google"].status, STATUS_ERROR)
        self.assertIn("quota exceeded", results["google"].error or "")

    def test_write_and_read_provider_access_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_file = Path(temp_dir) / "provider_access.json"
            initial = {
                "google": ProviderAccess(
                    provider="google",
                    masked_key="AQ.A...JqHA",
                    status=STATUS_OK,
                    model_ids=("gemini-2.5-flash", "gemini-2.5-pro"),
                    checked_at="2026-10-14T19:00:00Z",
                )
            }
            write_provider_access(cache_file, initial)
            self.assertTrue(cache_file.is_file())

            loaded = read_provider_access(cache_file)
            self.assertIn("google", loaded)
            self.assertEqual(loaded["google"].masked_key, "AQ.A...JqHA")
            self.assertEqual(loaded["google"].model_ids, ("gemini-2.5-flash", "gemini-2.5-pro"))

    def test_resolve_verified_access_warns_when_key_changes(self) -> None:
        cached = {
            "google": ProviderAccess(
                provider="google",
                masked_key="OLD_..._KEY",
                status=STATUS_OK,
                model_ids=("gemini-2.5-flash",),
            )
        }
        creds = {
            "google": ProviderCredentials(provider="google", is_available=True, source="env", masked_key="NEW_..._KEY"),
        }
        verified, diagnostics = resolve_verified_access(cached, creds, ["google"])
        self.assertNotIn("google", verified)
        self.assertTrue(any("a changé" in d for d in diagnostics))

    def test_router_falls_back_to_openrouter_when_model_not_on_direct_key(self) -> None:
        # Clé Google disponible, mais lyria-3 n'est PAS dans les modèles accessibles
        creds = {
            "google": ProviderCredentials(provider="google", is_available=True, source="env", masked_key="AQ.A...JqHA"),
            "openrouter": ProviderCredentials(provider="openrouter", is_available=True, source="env", masked_key="sk-o..."),
        }
        direct_access = {
            "google": frozenset({"gemini-2.5-flash", "gemma-4-26b-a4b-it"}),
        }

        # 1. Modèle accessible avec la clé Google -> routé sur Google Direct
        flash_model = Model("google/gemini-2.5-flash", "google", "pay_as_you_go", 0.075, 0.3, 1000000, True, 4)
        target_flash = resolve_model_execution_target(
            flash_model,
            provider_priority=["google", "openrouter"],
            credentials=creds,
            direct_access=direct_access,
        )
        self.assertEqual(target_flash.channel_provider, "google")
        self.assertEqual(target_flash.formatted_model_id, "google/gemini-2.5-flash")
        self.assertTrue(target_flash.access_verified)

        # 2. Modèle Google NON disponible avec cette clé -> bascule sur OpenRouter Proxy
        lyria_model = Model("google/lyria-3-clip-preview", "google", "pay_as_you_go", 0.1, 0.4, 32768, True, 3)
        target_lyria = resolve_model_execution_target(
            lyria_model,
            provider_priority=["google", "openrouter"],
            credentials=creds,
            direct_access=direct_access,
        )
        self.assertEqual(target_lyria.channel_provider, "openrouter")
        self.assertEqual(target_lyria.formatted_model_id, "openrouter/google/lyria-3-clip-preview")
        self.assertFalse(target_lyria.access_verified)


if __name__ == "__main__":
    unittest.main()
