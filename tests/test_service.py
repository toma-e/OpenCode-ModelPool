"""Tests du service applicatif partagé par le CLI et l'interface web."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
            with patch("src.service.sync_models_from_openrouter", side_effect=OSError("offline")):
                result = service.sync_catalogue()
            self.assertFalse(result.ok)
            self.assertIn("offline", result.message)
            self.assertEqual(service.models_path.read_text(encoding="utf-8"), before)

    def test_export_config_writes_opencode_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            write_valid_workspace(directory)
            service = ApplicationService(directory)
            result = service.export_config()
            self.assertTrue(result.ok)
            self.assertTrue(service.default_export_path.exists())

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


if __name__ == "__main__":
    unittest.main()

