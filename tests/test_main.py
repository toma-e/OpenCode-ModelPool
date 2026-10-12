"""Tests du point d'entrée CLI et du chargement validé."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main


class TestMain(unittest.TestCase):
    def _write_valid_files(self, directory: Path) -> None:
        (directory / "data").mkdir()
        (directory / "config").mkdir()
        (directory / "data" / "models.json").write_text(json.dumps({"models": [{
            "id": "test/model", "provider": "test", "tier": "free_tier",
            "cost_input_per_m": 0, "cost_output_per_m": 0, "context_window": 4096,
            "supports_tools": False, "complexity_score": 1,
        }]}), encoding="utf-8")
        (directory / "config" / "agents_requirements.json").write_text(json.dumps({"agents": [{
            "name": "agent", "description": "", "min_complexity": 1,
            "max_complexity": 1, "requires_tools": False, "prefer_free": True,
        }]}), encoding="utf-8")

    def test_load_data_rejects_corrupted_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            models = directory / "models.json"
            agents = directory / "agents.json"
            models.write_text("{", encoding="utf-8")
            agents.write_text('{"agents": []}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "JSON mal formé"):
                main.load_data(models, agents)

    def test_main_exports_with_explicit_argv(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self._write_valid_files(directory)
            args = main.build_parser().parse_args(["--export"])
            self.assertEqual(main.run(args, directory), 0)
            self.assertTrue((directory / "config" / "opencode.json").exists())

    def test_run_returns_one_when_sync_fails_without_rewriting_catalogue(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self._write_valid_files(directory)
            catalogue = directory / "data" / "models.json"
            before = catalogue.read_text(encoding="utf-8")
            args = main.build_parser().parse_args(["--sync"])
            with patch("src.service.fetch_openrouter_models", side_effect=OSError("offline")):
                self.assertEqual(main.run(args, directory), 1)
            self.assertEqual(catalogue.read_text(encoding="utf-8"), before)

    def test_parser_accepts_serve_default_port(self) -> None:
        args = main.build_parser().parse_args(["--serve"])
        self.assertEqual(args.serve, 8765)

    def test_parser_accepts_valid_serve_port(self) -> None:
        args = main.build_parser().parse_args(["--serve", "8080"])
        self.assertEqual(args.serve, 8080)

    def test_parser_rejects_invalid_serve_ports(self) -> None:
        parser = main.build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["--serve", "0"])
        with self.assertRaises(SystemExit):
            parser.parse_args(["--serve", "70000"])
        with self.assertRaises(SystemExit):
            parser.parse_args(["--serve", "not_a_number"])

    def test_run_returns_two_for_missing_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "data").mkdir()
            (directory / "data" / "models.json").write_text('{"models": []}', encoding="utf-8")
            args = main.build_parser().parse_args([])
            self.assertEqual(main.run(args, directory), 2)

    def test_run_custom_models_and_agents_and_validate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            custom_models = directory / "custom_models.json"
            custom_agents = directory / "custom_agents.json"
            custom_models.write_text(json.dumps({"models": [{
                "id": "vendor/model", "provider": "vendor", "tier": "free_tier",
                "cost_input_per_m": 0, "cost_output_per_m": 0, "context_window": 4096,
                "supports_tools": True, "complexity_score": 3,
            }]}), encoding="utf-8")
            custom_agents.write_text(json.dumps({"agents": [{
                "name": "tester", "description": "", "min_complexity": 3,
                "max_complexity": 3, "requires_tools": True, "prefer_free": True,
            }]}), encoding="utf-8")

            # Succès de validation
            args_valid = main.build_parser().parse_args([
                "--models", str(custom_models),
                "--agents", str(custom_agents),
                "--validate",
            ])
            self.assertEqual(main.run(args_valid, directory), 0)

            # Échec de validation si un agent exige un modèle incompatible
            custom_agents.write_text(json.dumps({"agents": [{
                "name": "impossible_agent", "description": "", "min_complexity": 5,
                "max_complexity": 5, "requires_tools": True, "prefer_free": True,
            }]}), encoding="utf-8")
            args_fail = main.build_parser().parse_args([
                "--models", str(custom_models),
                "--agents", str(custom_agents),
                "--validate",
                "--no-fallback",
            ])
            self.assertEqual(main.run(args_fail, directory), 1)

    def test_run_validate_and_export_chained(self) -> None:
        """Vérifie que le chaînage --validate et --export effectue bien la validation ET l'export."""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self._write_valid_files(directory)
            export_target = directory / "out_config.json"
            args = main.build_parser().parse_args(["--validate", "--export", str(export_target)])
            self.assertEqual(main.run(args, directory), 0)
            self.assertTrue(export_target.exists())


if __name__ == "__main__":
    unittest.main()
