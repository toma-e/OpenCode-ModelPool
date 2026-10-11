"""Tests unitaires pour le module d'export OpenCode exporter.py."""

import json
import tempfile
import unittest
from pathlib import Path

from src.exporter import (
    build_opencode_config,
    export_opencode_config,
    parse_json_or_jsonc,
)
from src.selector import (
    AgentRequirement,
    Model,
    SelectionResult,
)


class TestExporter(unittest.TestCase):
    def setUp(self) -> None:
        self.model = Model(
            id="test/model-fast",
            provider="test-provider",
            tier="free_tier",
            cost_input_per_m=0.0,
            cost_output_per_m=0.0,
            context_window=32000,
            supports_tools=True,
            complexity_score=3,
        )
        self.agent_req = AgentRequirement(
            name="coder_agent",
            description="Agent de code",
            min_complexity=3,
            max_complexity=4,
            requires_tools=True,
            prefer_free=True,
        )
        self.assigned_result = SelectionResult(
            agent_name="coder_agent",
            model=self.model,
            is_fallback=False,
            candidates=[self.model],
            reason="Correspondance exacte.",
        )
        self.unassigned_result = SelectionResult(
            agent_name="unknown_agent",
            model=None,
            is_fallback=False,
            candidates=[],
            reason="Aucun modèle compatible.",
        )

    def test_build_opencode_config_structure(self) -> None:
        config = build_opencode_config([self.assigned_result], [self.agent_req])
        self.assertEqual(config["$schema"], "https://opencode.ai/config.json")
        self.assertEqual(config["model"], "test/model-fast")
        self.assertEqual(config["version"], "1.0")
        self.assertEqual(config["metadata"]["total_agents"], 1)
        self.assertEqual(config["metadata"]["assigned_agents"], 1)
        self.assertEqual(config["metadata"]["unassigned_agents"], 0)
        self.assertTrue(config["generated_at"].endswith("+00:00"))

        # Section native OpenCode (agent[name])
        self.assertIn("coder_agent", config["agent"])
        native_coder = config["agent"]["coder_agent"]
        self.assertEqual(native_coder["model"], "test/model-fast")
        self.assertEqual(native_coder["mode"], "primary")
        self.assertEqual(native_coder["description"], "Agent de code")

        # Section ModelScope (agents[name]) pour rétrocompatibilité
        agent_entry = config["agents"]["coder_agent"]
        self.assertTrue(agent_entry["enabled"])
        self.assertEqual(agent_entry["selection_status"], "exact")
        self.assertIsNotNone(agent_entry["model"])
        self.assertEqual(agent_entry["model"]["id"], "test/model-fast")
        self.assertEqual(agent_entry["model"]["provider"], "test-provider")

    def test_build_opencode_config_unassigned(self) -> None:
        config = build_opencode_config([self.unassigned_result], [])
        self.assertEqual(config["metadata"]["assigned_agents"], 0)
        self.assertEqual(config["metadata"]["unassigned_agents"], 1)

        # Section native OpenCode
        self.assertIn("unknown_agent", config["agent"])
        self.assertTrue(config["agent"]["unknown_agent"]["disable"])

        # Section ModelScope
        agent_entry = config["agents"]["unknown_agent"]
        self.assertFalse(agent_entry["enabled"])
        self.assertEqual(agent_entry["selection_status"], "unassigned")
        self.assertIsNone(agent_entry["model"])

    def test_parse_json_or_jsonc(self) -> None:
        jsonc_sample = """
        {
            // Commentaire mono-ligne
            "$schema": "https://opencode.ai/config.json",
            /* Commentaire
               multi-lignes */
            "model": "openrouter/free",
            "permission": {
                "read": {"*": "allow"},
            },
        }
        """
        parsed = parse_json_or_jsonc(jsonc_sample)
        self.assertEqual(parsed["$schema"], "https://opencode.ai/config.json")
        self.assertEqual(parsed["model"], "openrouter/free")
        self.assertEqual(parsed["permission"]["read"]["*"], "allow")

        with self.assertRaises(ValueError):
            parse_json_or_jsonc("{ invalid json")

        with self.assertRaises(ValueError):
            parse_json_or_jsonc('["not", "a", "dict"]')

    def test_build_opencode_config_with_base_config(self) -> None:
        base = {
            "model": "openrouter/free",
            "permission": {"bash": {"*": "allow"}},
            "provider": {"ollama": {"name": "Ollama Local"}},
            "agent": {
                "custom_agent": {"model": "local/model", "mode": "subagent"}
            },
        }
        config = build_opencode_config(
            [self.assigned_result],
            [self.agent_req],
            base_config=base,
        )
        self.assertEqual(config["$schema"], "https://opencode.ai/config.json")
        self.assertEqual(config["model"], "openrouter/free")
        self.assertEqual(config["permission"]["bash"]["*"], "allow")
        self.assertEqual(config["provider"]["ollama"]["name"], "Ollama Local")
        self.assertIn("custom_agent", config["agent"])
        self.assertIn("coder_agent", config["agent"])
        self.assertEqual(config["agent"]["coder_agent"]["model"], "test/model-fast")

    def test_export_opencode_config_file_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_file = Path(tmp_dir) / "opencode_test.json"
            exported_path = export_opencode_config(
                [self.assigned_result], [self.agent_req], out_file
            )
            self.assertTrue(exported_path.exists())
            with open(exported_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            self.assertIn("coder_agent", loaded["agents"])
            self.assertIn("coder_agent", loaded["agent"])
            self.assertEqual(loaded["$schema"], "https://opencode.ai/config.json")


if __name__ == "__main__":
    unittest.main()
