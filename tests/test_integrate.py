"""Tests unitaires pour l'intégration de ModelPool dans OpenCode."""

import json
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from main import main
from src.service import ApplicationService


class TestIntegrateOpenCode(unittest.TestCase):
    """Vérifie l'intégration fluide de ModelPool dans OpenCode (fichiers, plugins, slash commands et MCP)."""

    def setUp(self) -> None:
        self.tmp_dir = TemporaryDirectory()
        self.base_dir = Path(self.tmp_dir.name)
        self.data_dir = self.base_dir / "data"
        self.config_dir = self.base_dir / "config"
        self.data_dir.mkdir(parents=True)
        self.config_dir.mkdir(parents=True)

        # Catalogue minimal
        self.models_file = self.data_dir / "models.json"
        self.models_file.write_text(
            json.dumps({
                "models": [
                    {
                        "id": "openrouter/fast-coder",
                        "provider": "openrouter",
                        "tier": "free_tier",
                        "context_window": 32000,
                        "supports_tools": True,
                        "supports_vision": False,
                        "supports_reasoning": False,
                        "complexity_score": 3,
                        "cost_input_per_m": 0.0,
                        "cost_output_per_m": 0.0,
                    },
                    {
                        "id": "mistral/codestral-latest",
                        "provider": "mistral",
                        "tier": "pay_as_you_go",
                        "context_window": 64000,
                        "supports_tools": True,
                        "supports_vision": False,
                        "supports_reasoning": False,
                        "complexity_score": 4,
                        "cost_input_per_m": 1.0,
                        "cost_output_per_m": 3.0,
                    },
                ]
            }),
            encoding="utf-8",
        )

        # Agents
        self.agents_file = self.config_dir / "agents_requirements.json"
        self.agents_file.write_text(
            json.dumps({
                "agents": [
                    {
                        "name": "build",
                        "description": "Agent de code",
                        "min_complexity": 3,
                        "max_complexity": 4,
                        "requires_tools": True,
                        "prefer_free": True,
                    },
                    {
                        "name": "plan",
                        "description": "Agent d'architecture",
                        "min_complexity": 3,
                        "max_complexity": 4,
                        "requires_tools": False,
                        "prefer_free": True,
                    },
                ]
            }),
            encoding="utf-8",
        )

        self.service = ApplicationService(self.base_dir)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_integrate_project_direct_copy(self) -> None:
        """Vérifie l'intégration dans un projet cible sous forme de copie directe."""
        project_dir = self.base_dir / "my_project"
        res = self.service.integrate_with_opencode(
            target="project",
            project_path=project_dir,
            use_symlink=False,
            enable_mcp=True,
            enable_commands=True,
        )
        self.assertTrue(res.ok)
        opencode_json = project_dir / ".opencode" / "opencode.json"
        self.assertTrue(opencode_json.exists())

        config = json.loads(opencode_json.read_text(encoding="utf-8"))
        self.assertEqual(config["$schema"], "https://opencode.ai/config.json")
        self.assertIn("build", config["agent"])
        self.assertIn("plan", config["agent"])

        # Vérification des commandes slash
        self.assertIn("command", config)
        self.assertIn("modelpool", config["command"])
        self.assertIn("modelpool-sync", config["command"])
        self.assertIn("modelpool-failover", config["command"])

        # Vérification de l'enregistrement MCP
        self.assertIn("mcp", config)
        self.assertIn("modelpool", config["mcp"])
        self.assertEqual(config["mcp"]["modelpool"]["type"], "local")
        self.assertTrue(config["mcp"]["modelpool"]["enabled"])

        # Vérification de la présence des plugins
        plugins_dir = project_dir / ".opencode" / "plugins"
        self.assertTrue((plugins_dir / "modelpool.mjs").exists())
        self.assertTrue((plugins_dir / "modelpool-fallback.mjs").exists())
        self.assertTrue((project_dir / ".opencode" / "rate-limit-fallback.json").exists())
        self.assertTrue((project_dir / ".opencode" / "modelpool-report.json").exists())

    def test_integrate_preserves_existing_config(self) -> None:
        """Vérifie que les permissions et providers existants sont rigoureusement préservés."""
        project_dir = self.base_dir / "existing_proj" / ".opencode"
        project_dir.mkdir(parents=True)
        existing_file = project_dir / "opencode.json"
        existing_file.write_text(
            json.dumps({
                "$schema": "https://opencode.ai/config.json",
                "permission": {
                    "bash": {"*": "allow", "rm -rf *": "deny"},
                },
                "provider": {
                    "my-custom-provider": {"name": "Custom Endpoint"},
                },
                "command": {
                    "my-test-command": {"description": "Custom user test command"},
                },
                "mcp": {
                    "other-mcp": {"type": "local", "command": ["npx", "other-server"]},
                },
            }),
            encoding="utf-8",
        )

        res = self.service.integrate_with_opencode(
            target="project",
            project_path=project_dir,
            use_symlink=False,
            enable_mcp=True,
            enable_commands=True,
        )
        self.assertTrue(res.ok)

        merged = json.loads(existing_file.read_text(encoding="utf-8"))
        # Permissions conservées
        self.assertEqual(merged["permission"]["bash"]["rm -rf *"], "deny")
        # Provider personnalisé conservé
        self.assertIn("my-custom-provider", merged["provider"])
        # Commandes fusionnées
        self.assertIn("my-test-command", merged["command"])
        self.assertIn("modelpool", merged["command"])
        # MCP fusionné
        self.assertIn("other-mcp", merged["mcp"])
        self.assertIn("modelpool", merged["mcp"])

    def test_integrate_symlink_mode(self) -> None:
        """Vérifie l'intégration via un lien symbolique."""
        project_dir = self.base_dir / "symlink_proj"
        res = self.service.integrate_with_opencode(
            target="project",
            project_path=project_dir,
            use_symlink=True,
            enable_mcp=True,
            enable_commands=True,
        )
        self.assertTrue(res.ok)
        symlink_target = project_dir / ".opencode" / "opencode.json"
        self.assertTrue(symlink_target.is_symlink())
        self.assertTrue(symlink_target.resolve().exists())

    def test_cli_integrate(self) -> None:
        """Vérifie la commande CLI python3 main.py --integrate."""
        project_dir = self.base_dir / "cli_proj"
        code = main([
            "--integrate",
            "--project",
            str(project_dir),
            "--models",
            str(self.models_file),
            "--agents",
            str(self.agents_file),
        ])
        self.assertEqual(code, 0)
        self.assertTrue((project_dir / ".opencode" / "opencode.json").exists())

    def test_watch_and_sync_triggers_on_change(self) -> None:
        """Vérifie que watch_and_sync détecte les modifications et ré-exporte."""
        target_export = self.base_dir / "watched_export.json"
        stop_event = threading.Event()
        changes_detected: list[str] = []

        def on_change(msg: str) -> None:
            changes_detected.append(msg)
            stop_event.set()

        # Démarrer watch_and_sync dans un thread
        watcher_thread = threading.Thread(
            target=self.service.watch_and_sync,
            kwargs={
                "export_path": target_export,
                "interval_seconds": 0.05,
                "stop_event": stop_event,
                "on_change": on_change,
            },
            daemon=True,
        )
        watcher_thread.start()

        # Simuler une mise à jour d'un fichier surveillé
        time.sleep(0.08)
        agents_data = json.loads(self.agents_file.read_text(encoding="utf-8"))
        agents_data["agents"][0]["description"] = "Description modifiée"
        self.agents_file.write_text(json.dumps(agents_data), encoding="utf-8")

        watcher_thread.join(timeout=2.0)
        self.assertTrue(len(changes_detected) > 0)
        self.assertTrue(target_export.exists())


if __name__ == "__main__":
    unittest.main()
