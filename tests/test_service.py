"""Tests du service applicatif partagé par le CLI et l'interface web."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.selector import resolve_model_for_agent
from src.service import ApplicationService, load_data, serialize_report


def write_valid_workspace(directory: Path, extra_model: bool = True) -> None:
    (directory / "data").mkdir()
    (directory / "config").mkdir()
    models = [
        {
            "id": "test/model",
            "provider": "test",
            "tier": "free_tier",
            "cost_input_per_m": 0,
            "cost_output_per_m": 0,
            "context_window": 4096,
            "supports_tools": False,
            "complexity_score": 1,
        }
    ]
    if extra_model:
        models.append(
            {
                "id": "test/alt",
                "provider": "test",
                "tier": "pay_as_you_go",
                "cost_input_per_m": 1,
                "cost_output_per_m": 1,
                "context_window": 8192,
                "supports_tools": False,
                "complexity_score": 1,
            }
        )
    (directory / "data" / "models.json").write_text(
        json.dumps({"last_updated": "2026-10-10T00:00:00+00:00", "models": models}),
        encoding="utf-8",
    )
    (directory / "config" / "agents_requirements.json").write_text(
        json.dumps(
            {
                "agents": [
                    {
                        "name": "agent",
                        "description": "",
                        "min_complexity": 1,
                        "max_complexity": 1,
                        "requires_tools": False,
                        "prefer_free": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


class TestService(unittest.TestCase):
    def test_load_data_rejects_corrupted_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            models = directory / "models.json"
            agents = directory / "agents.json"
            models.write_text("{", encoding="utf-8")
            agents.write_text('{"agents": []}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "JSON mal formé"):
                load_data(models, agents)

    def test_build_report_matches_selector_on_same_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            write_valid_workspace(directory)
            service = ApplicationService(directory)
            report = service.build_report()
            models, agents = load_data(service.models_path, service.agents_path)
            expected = [resolve_model_for_agent(agent, models) for agent in agents]
            self.assertEqual(len(report.results), len(expected))
            self.assertEqual(report.results[0].model.id if report.results[0].model else None, expected[0].model.id if expected[0].model else None)
            self.assertEqual(report.results[0].reason, expected[0].reason)
            payload = serialize_report(report)
            self.assertEqual(payload["assignments"][0]["model"]["id"], "test/model")
            self.assertEqual(payload["assignments"][0]["alternatives"][0]["id"], "test/alt")
            self.assertEqual(payload["catalogue"]["last_updated"], "2026-10-10T00:00:00+00:00")

    def test_sync_failure_does_not_rewrite_catalogue(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            write_valid_workspace(directory)
            service = ApplicationService(directory)
            before = service.models_path.read_text(encoding="utf-8")
            with patch("src.service.fetch_openrouter_models", side_effect=OSError("offline")):
                result = service.sync_catalogue()
            self.assertFalse(result.ok)
            self.assertIn("offline", result.message)
            self.assertEqual(service.models_path.read_text(encoding="utf-8"), before)

    def test_sync_catalogue_success_flow(self) -> None:
        """Vérifie le cycle complet de sync_catalogue avec modèles récupérés hors verrou."""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            write_valid_workspace(directory)
            service = ApplicationService(directory)
            fake_raw_models = [
                {
                    "id": f"provider/model-{i}",
                    "pricing": {"prompt": "0.000001", "completion": "0.000002"},
                    "context_length": 8192,
                    "supported_parameters": ["tools"],
                }
                for i in range(15)
            ]
            with patch("src.service.fetch_openrouter_models", return_value=fake_raw_models):
                result = service.sync_catalogue()
            self.assertTrue(result.ok)
            self.assertIn("15 modèles synchronisés", result.message)
            self.assertIsNotNone(result.report)
            self.assertEqual(len(result.report.models), 15)

    def test_export_config_writes_opencode_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            write_valid_workspace(directory)
            service = ApplicationService(directory)
            result = service.export_config()
            self.assertTrue(result.ok)
            self.assertTrue(service.default_export_path.exists())
            report_path = service.default_export_path.parent / "modelscope-report.json"
            self.assertTrue(report_path.exists())
            loaded_report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(loaded_report["version"], "1.0")
            self.assertIn("agent", loaded_report["agents"])

    def test_export_config_merges_base_opencode_config_from_ressources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            write_valid_workspace(directory)
            ressources_dir = directory / "Ressources"
            ressources_dir.mkdir()
            (ressources_dir / "opencode.jsonc").write_text(
                json.dumps({
                    "$schema": "https://opencode.ai/config.json",
                    "model": "openrouter/free",
                    "permission": {"bash": {"*": "allow"}},
                    "provider": {"ollama": {"name": "Ollama Local"}},
                }),
                encoding="utf-8",
            )
            service = ApplicationService(directory)
            result = service.export_config()
            self.assertTrue(result.ok)
            loaded = json.loads(service.default_export_path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["permission"]["bash"]["*"], "allow")
            self.assertEqual(loaded["provider"]["ollama"]["name"], "Ollama Local")
            self.assertIn("agent", loaded["agent"])

    def test_export_config_fails_explicitly_on_corrupted_base_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            write_valid_workspace(directory)
            ressources_dir = directory / "Ressources"
            ressources_dir.mkdir()
            (ressources_dir / "opencode.jsonc").write_text("{ unclosed invalid json", encoding="utf-8")
            service = ApplicationService(directory)
            result = service.export_config()
            self.assertFalse(result.ok)
            self.assertIn("invalide", result.message)

    def test_update_agent_requirement_success(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            write_valid_workspace(directory)
            service = ApplicationService(directory)
            result = service.update_agent_requirement(
                "agent",
                {"sort_strategy": "max_performance", "allow_free": False, "prefer_free": False},
            )
            self.assertTrue(result.ok)
            self.assertIn("mises à jour", result.message)
            # Vérifier la persistance dans le fichier JSON
            saved_agents = json.loads(service.agents_path.read_text(encoding="utf-8"))["agents"]
            agent_data = saved_agents[0]
            self.assertEqual(agent_data["sort_strategy"], "max_performance")
            self.assertFalse(agent_data["allow_free"])
            # Vérifier le rapport renvoyé
            self.assertIsNotNone(result.report)
            self.assertEqual(result.report.results[0].model.id, "test/alt")  # test/model exclu car gratuit

    def test_update_agent_requirement_invalid_validation_rejects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            write_valid_workspace(directory)
            service = ApplicationService(directory)
            # Contradiction allow_free=False et prefer_free=True
            result = service.update_agent_requirement(
                "agent",
                {"allow_free": False, "prefer_free": True},
            )
            self.assertFalse(result.ok)
            self.assertIn("Validation échouée", result.message)

    def test_file_lock_mechanism(self) -> None:
        """Vérifie que le verrou inter-processus crée le fichier .modelscope.lock et s'exécute sans erreur."""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            write_valid_workspace(directory)
            service = ApplicationService(directory)
            # Test direct du contextmanager _file_lock
            with service._file_lock():
                self.assertTrue(service._lock_path.exists())
            # Vérifier que les écritures sous verrou fonctionnent correctement
            result = service.export_config()
            self.assertTrue(result.ok)

    def test_file_lock_msvcrt_on_windows(self) -> None:
        """Simule un environnement Windows sans fcntl avec msvcrt disponible."""
        mock_msvcrt = MagicMock()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            write_valid_workspace(directory)
            service = ApplicationService(directory)
            with patch("src.service.fcntl", None), patch("src.service.msvcrt", mock_msvcrt):
                with service._file_lock():
                    mock_msvcrt.locking.assert_called_once()
                self.assertEqual(mock_msvcrt.locking.call_count, 2)  # lock + unlock

    def test_catalogue_freshness_warning(self) -> None:
        """Vérifie qu'une alerte est émise dans les diagnostics si le catalogue date de plus de 14 jours."""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            write_valid_workspace(directory)
            # Écrire une date ancienne (ex: il y a 60 jours)
            models_file = directory / "data" / "models.json"
            data = json.loads(models_file.read_text(encoding="utf-8"))
            data["last_updated"] = "2020-01-01T00:00:00+00:00"
            models_file.write_text(json.dumps(data), encoding="utf-8")

            service = ApplicationService(directory)
            report = service.build_report()
            matching_diag = [d for d in report.diagnostics if "Le catalogue date de plus de" in d]
            self.assertTrue(bool(matching_diag))
            self.assertIn("2020-01-01", matching_diag[0])
            self.assertIn("python3 main.py --sync", matching_diag[0])

    def test_catalogue_fresh_no_warning(self) -> None:
        """Vérifie qu'aucune alerte n'est émise si le catalogue est récent."""
        from datetime import datetime, timezone
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            write_valid_workspace(directory)
            models_file = directory / "data" / "models.json"
            data = json.loads(models_file.read_text(encoding="utf-8"))
            data["last_updated"] = datetime.now(timezone.utc).isoformat()
            models_file.write_text(json.dumps(data), encoding="utf-8")

            service = ApplicationService(directory)
            report = service.build_report()
            matching_diag = [d for d in report.diagnostics if "Le catalogue date de plus de" in d]
            self.assertEqual(len(matching_diag), 0)

    def test_resolve_export_path_expands_tilde(self) -> None:
        """Vérifie que les chemins d'export avec ~ sont correctement résolus en absolu."""
        service = ApplicationService(Path("/dummy/base"))
        resolved = service.resolve_export_path("~/.config/opencode/opencode.json")
        self.assertTrue(resolved.is_absolute())
        self.assertNotIn("~", str(resolved))
        self.assertTrue(str(resolved).endswith(".config/opencode/opencode.json"))


if __name__ == "__main__":
    unittest.main()

