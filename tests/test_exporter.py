"""Tests unitaires pour le module d'export OpenCode exporter.py."""

import json
import tempfile
import unittest
from pathlib import Path

from src.exporter import (
    build_modelpool_report_data,
    build_modelscope_report_data,
    build_opencode_config,
    format_opencode_model_id,
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
        self.assertEqual(config["model"], "openrouter/test/model-fast")

        # Vérifier que les clés interdites par OpenCode sont absentes de la config OpenCode
        self.assertNotIn("metadata", config)
        self.assertNotIn("budget_simulation", config)
        self.assertNotIn("agents", config)
        self.assertNotIn("version", config)

        # Section native OpenCode (agent[name])
        self.assertIn("coder_agent", config["agent"])
        native_coder = config["agent"]["coder_agent"]
        self.assertEqual(native_coder["model"], "openrouter/test/model-fast")
        self.assertEqual(native_coder["mode"], "primary")
        self.assertEqual(native_coder["description"], "Agent de code")

    def test_build_modelpool_report_data(self) -> None:
        self.assertIs(build_modelscope_report_data, build_modelpool_report_data)
        report = build_modelpool_report_data([self.assigned_result], [self.agent_req])
        self.assertEqual(report["version"], "1.0")
        self.assertEqual(report["metadata"]["generator"], "OpenCode-ModelPool")
        self.assertEqual(report["metadata"]["total_agents"], 1)
        self.assertEqual(report["metadata"]["assigned_agents"], 1)
        self.assertEqual(report["metadata"]["unassigned_agents"], 0)
        self.assertTrue(report["generated_at"].endswith("+00:00"))

        agent_entry = report["agents"]["coder_agent"]
        self.assertTrue(agent_entry["enabled"])
        self.assertEqual(agent_entry["selection_status"], "exact")
        self.assertIsNotNone(agent_entry["model"])
        self.assertEqual(agent_entry["model"]["id"], "test/model-fast")
        self.assertEqual(agent_entry["model"]["provider"], "test-provider")

    def test_build_opencode_config_unassigned(self) -> None:
        config = build_opencode_config([self.unassigned_result], [])
        self.assertIn("unknown_agent", config["agent"])
        self.assertTrue(config["agent"]["unknown_agent"]["disable"])

        report = build_modelpool_report_data([self.unassigned_result], [])
        self.assertEqual(report["metadata"]["assigned_agents"], 0)
        self.assertEqual(report["metadata"]["unassigned_agents"], 1)
        agent_entry = report["agents"]["unknown_agent"]
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

        # Cas critique : URL avec double slash et chaînes avec virgules
        complex_sample = """
        {
            "url": "https://example.com/api//v1",
            "regex": "foo, bar, } baz",
            "tags": ["a", "b", ],
        }
        """
        complex_parsed = parse_json_or_jsonc(complex_sample)
        self.assertEqual(complex_parsed["url"], "https://example.com/api//v1")
        self.assertEqual(complex_parsed["regex"], "foo, bar, } baz")
        self.assertEqual(complex_parsed["tags"], ["a", "b"])

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
        self.assertEqual(config["agent"]["coder_agent"]["model"], "openrouter/test/model-fast")

    def test_format_opencode_model_id_preserves_custom_provider(self) -> None:
        """Vérifie que les identifiants de modèles de fournisseurs locaux déclarés ne sont pas forcés vers openrouter."""
        from src.exporter import format_opencode_model_id

        base_config = {
            "provider": {
                "ollama": {"name": "Ollama Local"},
                "bedrock": {"name": "AWS Bedrock"},
            }
        }
        # Fournisseur déclaré dans base_config -> non altéré
        self.assertEqual(
            format_opencode_model_id("ollama/qwen3.5:9b", base_config=base_config),
            "ollama/qwen3.5:9b",
        )
        self.assertEqual(
            format_opencode_model_id("bedrock/anthropic.claude-v2", base_config=base_config),
            "bedrock/anthropic.claude-v2",
        )
        # Modèle OpenRouter ou sans préfixe déclaré -> préfixe openrouter/ ajouté
        self.assertEqual(
            format_opencode_model_id("openai/gpt-4o", base_config=base_config),
            "openrouter/openai/gpt-4o",
        )
        # Modèle déjà préfixé par openrouter -> idempotent
        self.assertEqual(
            format_opencode_model_id("openrouter/openai/gpt-4o", base_config=base_config),
            "openrouter/openai/gpt-4o",
        )

    def test_build_opencode_config_and_report_pure_data(self) -> None:
        """Vérifie la génération pure des structures de données OpenCode et rapport."""
        config = build_opencode_config([self.assigned_result], [self.agent_req])
        self.assertIn("coder_agent", config["agent"])
        self.assertNotIn("agents", config)
        self.assertEqual(config["$schema"], "https://opencode.ai/config.json")

        report = build_modelpool_report_data([self.assigned_result], [self.agent_req])
        self.assertIn("coder_agent", report["agents"])
        self.assertEqual(report["version"], "1.0")

    def test_build_opencode_config_native_modes(self) -> None:
        """Vérifie que 'build' et 'plan' deviennent 'primary' par défaut et que 'explore'/'general' deviennent 'subagent'."""
        agents = [
            AgentRequirement("build", "Build agent", 4, 5, True, False),
            AgentRequirement("plan", "Plan agent", 4, 5, False, False),
            AgentRequirement("explore", "Explore agent", 2, 3, False, True),
            AgentRequirement("general", "General agent", 3, 4, True, False),
        ]
        results = [
            SelectionResult(a.name, self.model, False, [self.model], "ok") for a in agents
        ]
        config = build_opencode_config(results, agents)
        self.assertEqual(config["agent"]["build"]["mode"], "primary")
        self.assertEqual(config["agent"]["plan"]["mode"], "primary")
        self.assertEqual(config["agent"]["explore"]["mode"], "subagent")
        self.assertEqual(config["agent"]["general"]["mode"], "subagent")


if __name__ == "__main__":
    unittest.main()
