"""Tests unitaires pour le serveur Model Context Protocol (MCP) de ModelPool."""

import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.mcp_server import ModelPoolMCPServer, run_mcp_server
from src.service import ApplicationService


class TestModelPoolMCPServer(unittest.TestCase):
    """Vérifie le respect du protocole MCP et l'exécution correcte des outils."""

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
                        "id": "provider/free-model",
                        "name": "Free Fast Model",
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
                        "id": "provider/paid-model",
                        "name": "Paid Pro Model",
                        "provider": "openrouter",
                        "tier": "pay_as_you_go",
                        "context_window": 128000,
                        "supports_tools": True,
                        "supports_vision": True,
                        "supports_reasoning": True,
                        "complexity_score": 5,
                        "cost_input_per_m": 2.5,
                        "cost_output_per_m": 10.0,
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
                        "max_complexity": 5,
                        "requires_tools": True,
                        "prefer_free": True,
                    },
                    {
                        "name": "plan",
                        "description": "Agent d'architecture",
                        "min_complexity": 4,
                        "max_complexity": 5,
                        "requires_tools": False,
                        "prefer_free": False,
                    },
                ]
            }),
            encoding="utf-8",
        )

        self.service = ApplicationService(self.base_dir)
        self.server = ModelPoolMCPServer(self.service)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_initialize(self) -> None:
        req = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        resp = self.server.handle_request(req)
        self.assertIsNotNone(resp)
        self.assertEqual(resp["id"], 1)
        self.assertEqual(resp["result"]["protocolVersion"], "2024-11-05")
        self.assertEqual(resp["result"]["serverInfo"]["name"], "opencode-modelpool")
        self.assertIn("tools", resp["result"]["capabilities"])

    def test_ping(self) -> None:
        req = {"jsonrpc": "2.0", "id": 42, "method": "ping"}
        resp = self.server.handle_request(req)
        self.assertEqual(resp, {"jsonrpc": "2.0", "id": 42, "result": {}})

    def test_notifications_ignored(self) -> None:
        req = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        resp = self.server.handle_request(req)
        self.assertIsNone(resp)

    def test_tools_list(self) -> None:
        req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        resp = self.server.handle_request(req)
        self.assertIsNotNone(resp)
        tools = resp["result"]["tools"]
        tool_names = [t["name"] for t in tools]
        self.assertIn("modelpool_status", tool_names)
        self.assertIn("modelpool_switch_strategy", tool_names)
        self.assertIn("modelpool_report_issue", tool_names)
        self.assertIn("modelpool_list_models", tool_names)

    def test_tools_call_status(self) -> None:
        req = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "modelpool_status", "arguments": {}},
        }
        resp = self.server.handle_request(req)
        self.assertIsNotNone(resp)
        self.assertFalse(resp["result"]["isError"])
        content_text = resp["result"]["content"][0]["text"]
        self.assertIn("Statut OpenCode-ModelPool", content_text)
        self.assertIn("build", content_text)
        self.assertIn("plan", content_text)

    def test_tools_call_switch_strategy(self) -> None:
        req = {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "modelpool_switch_strategy",
                "arguments": {
                    "agent_name": "build",
                    "reliability_preference": "prefer_stability",
                    "prefer_free": False,
                },
            },
        }
        resp = self.server.handle_request(req)
        self.assertIsNotNone(resp)
        self.assertFalse(resp["result"]["isError"])
        self.assertIn("✅ Stratégie de l'agent 'build' mise à jour", resp["result"]["content"][0]["text"])

        # Vérification de persistance
        report = self.service.build_report(allow_fallback=True)
        build_agent = next(a for a in report.agents if a.name == "build")
        self.assertEqual(build_agent.reliability_preference, "prefer_stability")
        self.assertFalse(build_agent.prefer_free)

    def test_tools_call_report_issue(self) -> None:
        req = {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "modelpool_report_issue",
                "arguments": {
                    "target_or_agent": "build",
                    "reason": "rate_limit",
                    "cooldown_minutes": 10,
                },
            },
        }
        resp = self.server.handle_request(req)
        self.assertIsNotNone(resp)
        self.assertFalse(resp["result"]["isError"])
        self.assertIn("Incident signalé", resp["result"]["content"][0]["text"])

        # Vérifier la présence en quarantaine
        cooldowns = self.service.get_active_cooldowns()
        self.assertTrue(len(cooldowns) > 0)

    def test_tools_call_list_models(self) -> None:
        # Recherche par mot-clé
        req = {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {
                "name": "modelpool_list_models",
                "arguments": {"query": "paid", "only_free": False},
            },
        }
        resp = self.server.handle_request(req)
        self.assertFalse(resp["result"]["isError"])
        self.assertIn("provider/paid-model", resp["result"]["content"][0]["text"])
        self.assertNotIn("provider/free-model", resp["result"]["content"][0]["text"])

        # Filtrage modèles gratuits
        req_free = {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "modelpool_list_models",
                "arguments": {"only_free": True},
            },
        }
        resp_free = self.server.handle_request(req_free)
        self.assertIn("provider/free-model", resp_free["result"]["content"][0]["text"])
        self.assertNotIn("provider/paid-model", resp_free["result"]["content"][0]["text"])

    def test_tools_call_unknown_tool(self) -> None:
        req = {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {"name": "non_existent_tool", "arguments": {}},
        }
        resp = self.server.handle_request(req)
        self.assertIn("error", resp)
        self.assertEqual(resp["error"]["code"], -32602)

    def test_run_mcp_server_loop(self) -> None:
        lines = [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}),
            "",
            "malformed json",
        ]
        in_io = io.StringIO("\n".join(lines) + "\n")
        out_io = io.StringIO()

        run_mcp_server(self.service, in_stream=in_io, out_stream=out_io)
        output = out_io.getvalue().strip().split("\n")
        self.assertEqual(len(output), 3)

        resp1 = json.loads(output[0])
        self.assertEqual(resp1["id"], 1)
        resp2 = json.loads(output[1])
        self.assertEqual(resp2["id"], 2)
        resp3 = json.loads(output[2])
        self.assertIn("error", resp3)
        self.assertEqual(resp3["error"]["code"], -32700)


if __name__ == "__main__":
    unittest.main()
