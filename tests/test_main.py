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
        (directory / "data" / "models.json").write_text(json.dumps({
            "last_updated": "2026-10-10T00:00:00+00:00",
            "models": [{
                "id": "test/model", "provider": "test", "tier": "free_tier",
                "cost_input_per_m": 0, "cost_output_per_m": 0, "context_window": 4096,
                "supports_tools": False, "complexity_score": 1,
            }]
        }), encoding="utf-8")
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

    def test_render_results_displays_diagnostics(self) -> None:
        """Vérifie que les avertissements/diagnostics sont bien imprimés par render_results."""
        import io
        from contextlib import redirect_stdout
        from src.budget import FleetBudgetReport
        from src.selector import SelectionResult
        from src.service import FleetReport

        report = FleetReport(
            models=[],
            agents=[],
            results=[],
            budget=FleetBudgetReport(0.0, 0, 0.0, []),
            catalogue_updated_at=None,
            diagnostics=["Alerte test diagnostic"],
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            main.render_results(report)
        output = buf.getvalue()
        self.assertIn("⚠️  Diagnostics :", output)
        self.assertIn("Alerte test diagnostic", output)


    def test_provider_priority_arg(self) -> None:
        """Vérifie que l'option --provider-priority est acceptée et transmise."""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self._write_valid_files(directory)
            args = main.build_parser().parse_args(["--provider-priority", "ollama,groq,openrouter"])
            self.assertEqual(args.provider_priority, "ollama,groq,openrouter")
            self.assertEqual(main.run(args, directory), 0)

    def test_sync_openrouter_and_sync_all_flags(self) -> None:
        """MP-202 : Vérifie l'aiguillage CLI entre --sync-openrouter et --sync-all."""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self._write_valid_files(directory)

            # Test --sync-openrouter
            args_or = main.build_parser().parse_args(["--sync-openrouter"])
            with patch("src.service.ApplicationService.sync_catalogue") as mock_sync:
                from src.service import OperationResult
                mock_sync.return_value = OperationResult(True, "10 modèles")
                ret = main.run(args_or, directory)
                self.assertEqual(ret, 0)
                mock_sync.assert_called_once()
                _, kwargs = mock_sync.call_args
                self.assertFalse(kwargs.get("multi_provider", True))

            # Test --sync-all
            args_all = main.build_parser().parse_args(["--sync-all"])
            with patch("src.service.ApplicationService.sync_catalogue") as mock_sync_all:
                mock_sync_all.return_value = OperationResult(True, "50 modèles")
                ret = main.run(args_all, directory)
                self.assertEqual(ret, 0)
                mock_sync_all.assert_called_once()
                _, kwargs = mock_sync_all.call_args
                self.assertTrue(kwargs.get("multi_provider", False))

    def test_check_ready_cli_flag(self) -> None:
        """MP-207 : Vérifie la commande CLI --check-ready (mode strict)."""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self._write_valid_files(directory)

            args = main.build_parser().parse_args(["--check-ready"])

            # Cas échec de readiness
            with patch("src.service.ApplicationService.check_fleet_readiness", return_value=(False, ["Clé manquante"])):
                ret_fail = main.run(args, directory)
                self.assertEqual(ret_fail, 1)

            # Cas succès de readiness
            with patch("src.service.ApplicationService.check_fleet_readiness", return_value=(True, [])):
                ret_ok = main.run(args, directory)
                self.assertEqual(ret_ok, 0)

    def test_diff_and_rollback_cli_flags(self) -> None:
        """MP-206 : Vérifie les commandes CLI --diff et --rollback."""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self._write_valid_files(directory)

            # Test --diff
            args_diff = main.build_parser().parse_args(["--diff"])
            with patch("src.service.ApplicationService.preview_export", return_value={
                "target_path": str(directory / "config" / "opencode.json"),
                "diff": "+ {\"model\": \"test\"}",
                "is_valid": True,
                "validation_errors": [],
            }):
                ret_diff = main.run(args_diff, directory)
                self.assertEqual(ret_diff, 0)

            # Test --rollback
            from src.service import OperationResult
            args_rb = main.build_parser().parse_args(["--rollback"])
            with patch("src.service.ApplicationService.rollback_export", return_value=OperationResult(True, "Restauré")):
                ret_rb = main.run(args_rb, directory)
                self.assertEqual(ret_rb, 0)

    def test_sync_if_stale_flag(self) -> None:
        """Vérifie le déclenchement conditionnel de --sync-if-stale."""
        parser = main.build_parser()
        args_default = parser.parse_args(["--sync-if-stale"])
        self.assertEqual(args_default.sync_if_stale, 14)

        args_custom = parser.parse_args(["--sync-if-stale", "7"])
        self.assertEqual(args_custom.sync_if_stale, 7)

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self._write_valid_files(directory)

            from src.service import OperationResult
            # Cas 1 : Catalogue non périmé -> aucune synchronisation déclenchée
            with patch("src.service.ApplicationService.is_catalogue_stale", return_value=(False, 3)), \
                 patch("src.service.ApplicationService.sync_catalogue") as mock_sync:
                ret = main.run(args_default, directory)
                self.assertEqual(ret, 0)
                mock_sync.assert_not_called()

            # Cas 2 : Catalogue périmé -> synchronisation déclenchée
            with patch("src.service.ApplicationService.is_catalogue_stale", return_value=(True, 20)), \
                 patch("src.service.ApplicationService.sync_catalogue", return_value=OperationResult(True, "OK")) as mock_sync:
                ret = main.run(args_default, directory)
                self.assertEqual(ret, 0)
                mock_sync.assert_called_once()

    def test_presets_cli_flags(self) -> None:
        """Vérifie les drapeaux CLI --list-presets et --add-preset."""
        parser = main.build_parser()
        args_list = parser.parse_args(["--list-presets"])
        self.assertTrue(args_list.list_presets)

        args_add = parser.parse_args(["--add-preset", "code_reviewer", "mon_auditeur"])
        self.assertEqual(args_add.add_preset, ["code_reviewer", "mon_auditeur"])

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self._write_valid_files(directory)

            # Test --list-presets
            ret_list = main.run(args_list, directory)
            self.assertEqual(ret_list, 0)

            # Test --add-preset
            ret_add = main.run(args_add, directory)
            self.assertEqual(ret_add, 0)


if __name__ == "__main__":
    unittest.main()
