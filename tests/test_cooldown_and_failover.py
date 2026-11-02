"""Tests unitaires et d'intégration pour la quarantaine sur erreur (Cooldown) et le repli automatique (Failover)."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import main as cli_main
from src.cooldown import (
    REASON_AUTH_ERROR,
    REASON_INSUFFICIENT_CREDITS,
    REASON_OTHER,
    REASON_QUOTA_EXCEEDED,
    REASON_RATE_LIMIT,
    REASON_SERVICE_UNAVAILABLE,
    classify_error_reason,
    create_cooldown_entry,
    is_model_in_cooldown,
    is_provider_in_cooldown,
    read_cooldowns,
    write_cooldowns,
)
from src.exporter import (
    build_opencode_fallback_plugin_js,
    build_rate_limit_fallback_config,
    split_opencode_model_id,
)
from src.providers.detector import ProviderCredentials
from src.providers.router import resolve_model_execution_target
from src.selector import (
    AgentRequirement,
    Model,
    SelectionResult,
    build_hybrid_fallback_chain,
    resolve_model_for_agent,
)
from src.service import ApplicationService


class TestCooldownClassificationAndPersistence(unittest.TestCase):
    """Vérifie la classification des erreurs et la gestion du cycle de vie des quarantaines."""

    def test_classify_error_reason_by_status_and_message(self) -> None:
        self.assertEqual(classify_error_reason(429, "Rate limit reached for RPM"), REASON_RATE_LIMIT)
        self.assertEqual(
            classify_error_reason(429, "You have exceeded your daily limit (RPD quota exceeded)"),
            REASON_QUOTA_EXCEEDED,
        )
        self.assertEqual(classify_error_reason(402, "Insufficient credits"), REASON_INSUFFICIENT_CREDITS)
        self.assertEqual(
            classify_error_reason(429, "insufficient_quota: please check your billing details"),
            REASON_INSUFFICIENT_CREDITS,
        )
        self.assertEqual(classify_error_reason(503, "Model is currently overloaded"), REASON_SERVICE_UNAVAILABLE)
        self.assertEqual(classify_error_reason(504, "Upstream idle timeout exceeded"), REASON_SERVICE_UNAVAILABLE)
        self.assertEqual(classify_error_reason(None, "stream error: idle timeout"), REASON_SERVICE_UNAVAILABLE)
        self.assertEqual(classify_error_reason(401, "Invalid API Key"), REASON_AUTH_ERROR)
        self.assertEqual(classify_error_reason(400, "Unknown bad request"), REASON_OTHER)

    def test_cooldown_entry_ttl_and_expiration(self) -> None:
        now = datetime(2026, 10, 27, 18, 0, 0, tzinfo=timezone.utc)
        entry = create_cooldown_entry("openrouter/nvidia/nemotron:free", reason=REASON_RATE_LIMIT, now=now)
        self.assertTrue(entry.is_active(now=now + timedelta(minutes=5)))
        self.assertEqual(entry.remaining_seconds(now=now + timedelta(minutes=5)), 600)
        self.assertFalse(entry.is_active(now=now + timedelta(minutes=16)))
        self.assertEqual(entry.remaining_seconds(now=now + timedelta(minutes=16)), 0)

    def test_read_and_write_cooldowns_purges_expired(self) -> None:
        now = datetime(2026, 10, 27, 18, 0, 0, tzinfo=timezone.utc)
        active = create_cooldown_entry("groq/openai/gpt-oss-120b", reason=REASON_QUOTA_EXCEEDED, now=now)
        expired = create_cooldown_entry(
            "openrouter/google/gemma:free",
            reason=REASON_RATE_LIMIT,
            now=now - timedelta(hours=1),
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "model_cooldowns.json"
            write_cooldowns(path, [active, expired], now=now)
            loaded = read_cooldowns(path, now=now)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].target_id, "groq/openai/gpt-oss-120b")
            self.assertEqual(loaded[0].reason, REASON_QUOTA_EXCEEDED)

    def test_is_model_and_provider_in_cooldown_matching(self) -> None:
        now = datetime(2026, 10, 27, 18, 0, 0, tzinfo=timezone.utc)
        entries = [
            create_cooldown_entry("openrouter/nvidia/nemotron:free", reason=REASON_RATE_LIMIT, now=now),
            create_cooldown_entry("provider:groq", reason=REASON_QUOTA_EXCEEDED, now=now),
        ]
        # Correspondance avec ou sans préfixe openrouter/
        self.assertIsNotNone(
            is_model_in_cooldown("nvidia/nemotron:free", "openrouter/nvidia/nemotron:free", "openrouter", entries)
        )
        # Correspondance par provider entier
        self.assertIsNotNone(is_provider_in_cooldown("groq", entries))
        self.assertIsNotNone(
            is_model_in_cooldown("openai/gpt-oss-120b", "groq/openai/gpt-oss-120b", "groq", entries)
        )
        # Modèle sain sur un autre canal
        self.assertIsNone(
            is_model_in_cooldown("mistralai/codestral", "mistral/codestral", "mistralai", entries)
        )


class TestHybridFallbackAndSelectorExclusion(unittest.TestCase):
    """Vérifie la sélection pure avec exclusions et la chaîne de repli hybride."""

    def setUp(self) -> None:
        self.req = AgentRequirement(
            name="build",
            description="Agent principal",
            min_complexity=4,
            max_complexity=5,
            requires_tools=True,
            prefer_free=True,
        )
        self.m1 = Model(
            id="nvidia/nemotron:free",
            provider="nvidia",
            tier="free_tier",
            cost_input_per_m=0.0,
            cost_output_per_m=0.0,
            context_window=128000,
            supports_tools=True,
            complexity_score=5,
        )
        self.m2 = Model(
            id="google/gemma-4-31b:free",
            provider="google",
            tier="free_tier",
            cost_input_per_m=0.0,
            cost_output_per_m=0.0,
            context_window=128000,
            supports_tools=True,
            complexity_score=4,
        )

    def test_excluded_models_skips_quarantined_primary_and_forced(self) -> None:
        res_normal = resolve_model_for_agent(self.req, [self.m1, self.m2])
        self.assertIsNotNone(res_normal.model)
        # Si le modèle retenu (m2 car Google est Tier 1) est mis en quarantaine, bascule sur m1
        res_failover = resolve_model_for_agent(
            self.req,
            [self.m1, self.m2],
            excluded_models={"openrouter/google/gemma-4-31b:free"},
        )
        self.assertIsNotNone(res_failover.model)
        self.assertEqual(res_failover.model.id, "nvidia/nemotron:free")

        # Même si force_model est défini sur le modèle en quarantaine, bascule automatiquement
        forced_req = AgentRequirement(
            name="build",
            description="Agent principal",
            min_complexity=4,
            max_complexity=5,
            requires_tools=True,
            prefer_free=True,
            force_model="google/gemma-4-31b:free",
        )
        res_forced_failover = resolve_model_for_agent(
            forced_req,
            [self.m1, self.m2],
            excluded_models={"google/gemma-4-31b:free"},
        )
        self.assertTrue(res_forced_failover.is_fallback)
        self.assertIsNotNone(res_forced_failover.model)
        self.assertEqual(res_forced_failover.model.id, "nvidia/nemotron:free")
        self.assertIn("quarantaine", res_forced_failover.reason)

    def test_build_hybrid_fallback_chain_inter_then_intra_channel(self) -> None:
        # Cas où tous les candidats sont sur le même canal (openrouter) sauf un sur groq
        candidates = [
            ("openrouter/google/gemma-4-31b:free", "openrouter"),
            ("groq/openai/gpt-oss-120b", "groq"),
            ("openrouter/qwen/qwen3-coder:free", "openrouter"),
            ("openrouter/deepseek/deepseek-r1:free", "openrouter"),
        ]
        chain = build_hybrid_fallback_chain(
            primary_formatted_id="openrouter/nvidia/nemotron:free",
            primary_channel="openrouter",
            candidate_targets=candidates,
            max_length=3,
        )
        # Passe 1 doit prendre groq en premier (canal différent d'openrouter),
        # puis Passe 2 complète avec les modèles openrouter jusqu'à 3 !
        self.assertEqual(
            chain,
            [
                "groq/openai/gpt-oss-120b",
                "openrouter/google/gemma-4-31b:free",
                "openrouter/qwen/qwen3-coder:free",
            ],
        )

    def test_router_skips_excluded_direct_channel_to_openrouter(self) -> None:
        model = Model(
            id="mistralai/mistral-large-latest",
            provider="mistralai",
            tier="pay_as_you_go",
            cost_input_per_m=2.0,
            cost_output_per_m=6.0,
            context_window=128000,
            supports_tools=True,
            complexity_score=5,
        )
        creds = {
            "mistralai": ProviderCredentials("mistralai", True, "env", "sk-m..."),
            "openrouter": ProviderCredentials("openrouter", True, "env", "sk-or..."),
        }
        # Sans exclusion : choisit mistralai direct
        t1 = resolve_model_execution_target(
            model,
            ["mistralai", "openrouter"],
            creds,
            direct_access={"mistralai": {"mistral-large-latest"}},
        )
        self.assertEqual(t1.channel_provider, "mistralai")

        # Si mistral/mistral-large-latest est en quarantaine : bascule sur openrouter
        t2 = resolve_model_execution_target(
            model,
            ["mistralai", "openrouter"],
            creds,
            direct_access={"mistralai": {"mistral-large-latest"}},
            excluded_targets={"mistral/mistral-large-latest"},
        )
        self.assertEqual(t2.channel_provider, "openrouter")
        self.assertEqual(t2.formatted_model_id, "openrouter/mistralai/mistral-large-latest")


class TestExporterFallbackPluginAndServiceFailover(unittest.TestCase):
    """Vérifie la génération du plugin OpenCode et le flux complet de bascule via Service et CLI."""

    def test_split_opencode_model_id_and_fallback_config(self) -> None:
        self.assertEqual(
            split_opencode_model_id("openrouter/nvidia/nemotron:free"),
            ("openrouter", "nvidia/nemotron:free"),
        )
        self.assertEqual(
            split_opencode_model_id("groq/openai/gpt-oss-120b"),
            ("groq", "openai/gpt-oss-120b"),
        )
        self.assertEqual(
            split_opencode_model_id("ollama/qwen3.5:9b"),
            ("ollama", "qwen3.5:9b"),
        )

        m = Model("nvidia/nemotron:free", "nvidia", "free_tier", 0.0, 0.0, 128000, True, 5)
        res = SelectionResult("build", m, False, [m], "Exact")
        chains = {"build": ["groq/openai/gpt-oss-120b", "openrouter/google/gemma:free"]}

        cfg = build_rate_limit_fallback_config([res], fallback_chains=chains)
        self.assertTrue(cfg["enabled"])
        self.assertEqual(
            cfg["fallbackModels"],
            [
                {"providerID": "groq", "modelID": "openai/gpt-oss-120b"},
                {"providerID": "openrouter", "modelID": "google/gemma:free"},
            ],
        )

        js = build_opencode_fallback_plugin_js([res], fallback_chains=chains, project_dir="/app")
        self.assertIn("ModelPoolFallbackPlugin", js)
        self.assertIn("session.error", js)
        self.assertIn("client.session.prompt", js)
        self.assertIn("--failover", js)

    @patch("src.service.detect_provider_credentials", return_value={})
    @patch("src.service.get_ollama_models", return_value=[])
    def test_service_failover_and_cli_integration(self, _mock_ollama: object, _mock_creds: object) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "data").mkdir()
            (base / "config").mkdir()

            models_payload = {
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "models": [
                    {
                        "id": "google/gemma-4-31b:free",
                        "provider": "google",
                        "tier": "free_tier",
                        "cost_input_per_m": 0.0,
                        "cost_output_per_m": 0.0,
                        "context_window": 128000,
                        "supports_tools": True,
                        "complexity_score": 5,
                        "supports_reasoning": True,
                    },
                    {
                        "id": "nvidia/nemotron-3-ultra:free",
                        "provider": "nvidia",
                        "tier": "free_tier",
                        "cost_input_per_m": 0.0,
                        "cost_output_per_m": 0.0,
                        "context_window": 128000,
                        "supports_tools": True,
                        "complexity_score": 5,
                        "supports_reasoning": True,
                    },
                ],
            }
            agents_payload = {
                "agents": [
                    {
                        "name": "build",
                        "description": "Agent principal",
                        "min_complexity": 4,
                        "max_complexity": 5,
                        "requires_tools": True,
                        "prefer_free": True,
                        "requires_reasoning": True,
                    }
                ]
            }
            (base / "data" / "models.json").write_text(json.dumps(models_payload), encoding="utf-8")
            (base / "config" / "agents_requirements.json").write_text(json.dumps(agents_payload), encoding="utf-8")

            svc = ApplicationService(base)
            initial_export = svc.export_config()
            self.assertTrue(initial_export.ok)
            opencode_path = base / "config" / "opencode.json"
            fallback_json_path = base / "config" / "rate-limit-fallback.json"
            plugin_path = base / "config" / "plugins" / "modelpool-fallback.mjs"

            self.assertTrue(opencode_path.is_file())
            self.assertTrue(fallback_json_path.is_file())
            self.assertTrue(plugin_path.is_file())

            initial_cfg = json.loads(opencode_path.read_text(encoding="utf-8"))
            self.assertEqual(initial_cfg["agent"]["build"]["model"], "openrouter/google/gemma-4-31b:free")
            self.assertIn("plugin", initial_cfg)
            self.assertEqual(initial_cfg["plugin"], ["@azumag/opencode-rate-limit-fallback"])

            # Déclenchement d'une bascule (failover) sur l'agent 'build' via CLI
            parser = cli_main.build_parser()
            args = parser.parse_args(["--failover", "build", "--error-reason", "rate_limit"])
            buf = io.StringIO()
            with redirect_stdout(buf):
                exit_code = cli_main.run(args, base_dir=base)
            self.assertEqual(exit_code, 0)

            # Le fichier opencode.json doit maintenant utiliser le modèle de secours
            after_cfg = json.loads(opencode_path.read_text(encoding="utf-8"))
            self.assertEqual(after_cfg["agent"]["build"]["model"], "openrouter/nvidia/nemotron-3-ultra:free")

            # Vérifier --list-cooldowns
            args_list = parser.parse_args(["--list-cooldowns"])
            buf_list = io.StringIO()
            with redirect_stdout(buf_list):
                self.assertEqual(cli_main.run(args_list, base_dir=base), 0)
            self.assertIn("openrouter/google/gemma-4-31b:free", buf_list.getvalue())

            # Lever la quarantaine avec --clear-cooldowns et ré-exporter
            args_clear = parser.parse_args(["--clear-cooldowns", "--export"])
            buf_clear = io.StringIO()
            with redirect_stdout(buf_clear):
                self.assertEqual(cli_main.run(args_clear, base_dir=base), 0)

            restored_cfg = json.loads(opencode_path.read_text(encoding="utf-8"))
            self.assertEqual(restored_cfg["agent"]["build"]["model"], "openrouter/google/gemma-4-31b:free")

    @patch("src.service.detect_provider_credentials", return_value={})
    @patch("src.service.get_ollama_models", return_value=[])
    def test_export_syncs_to_global_opencode_dir(self, _mock_ollama: object, _mock_creds: object) -> None:
        """Vérifie que rate-limit-fallback.json est bien synchronisé dans ~/.config/opencode si le dossier existe."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "data").mkdir()
            (base / "config").mkdir()

            models_payload = {
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "models": [
                    {
                        "id": "google/gemma:free",
                        "provider": "google",
                        "tier": "free_tier",
                        "cost_input_per_m": 0.0,
                        "cost_output_per_m": 0.0,
                        "context_window": 128000,
                        "supports_tools": True,
                        "complexity_score": 5,
                    }
                ],
            }
            agents_payload = {
                "agents": [
                    {
                        "name": "build",
                        "description": "Agent principal",
                        "min_complexity": 4,
                        "max_complexity": 5,
                        "requires_tools": True,
                        "prefer_free": True,
                    }
                ]
            }
            (base / "data" / "models.json").write_text(json.dumps(models_payload), encoding="utf-8")
            (base / "config" / "agents_requirements.json").write_text(json.dumps(agents_payload), encoding="utf-8")

            fake_home = base / "user_home"
            fake_global_opencode = fake_home / ".config" / "opencode"
            fake_global_opencode.mkdir(parents=True)

            with patch("pathlib.Path.home", return_value=fake_home):
                svc = ApplicationService(base)
                res = svc.export_config()
                self.assertTrue(res.ok)
                self.assertTrue((fake_global_opencode / "rate-limit-fallback.json").is_file())
                self.assertTrue((fake_global_opencode / "plugins" / "modelpool-fallback.mjs").is_file())

    @patch("src.service.detect_provider_credentials", return_value={})
    @patch("src.service.get_ollama_models", return_value=[])
    def test_web_failover_and_clear_cooldowns_endpoints(self, _mock_ollama: object, _mock_creds: object) -> None:
        import threading
        import urllib.request
        from src.web import create_server

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "data").mkdir()
            (base / "config").mkdir()
            models_payload = {
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "models": [
                    {
                        "id": "google/gemma-4-31b:free",
                        "provider": "google",
                        "tier": "free_tier",
                        "cost_input_per_m": 0.0,
                        "cost_output_per_m": 0.0,
                        "context_window": 128000,
                        "supports_tools": True,
                        "complexity_score": 5,
                        "supports_reasoning": True,
                    },
                    {
                        "id": "nvidia/nemotron-3-ultra:free",
                        "provider": "nvidia",
                        "tier": "free_tier",
                        "cost_input_per_m": 0.0,
                        "cost_output_per_m": 0.0,
                        "context_window": 128000,
                        "supports_tools": True,
                        "complexity_score": 5,
                        "supports_reasoning": True,
                    },
                ],
            }
            agents_payload = {
                "agents": [
                    {
                        "name": "build",
                        "description": "Agent principal",
                        "min_complexity": 4,
                        "max_complexity": 5,
                        "requires_tools": True,
                        "prefer_free": True,
                        "requires_reasoning": True,
                    }
                ]
            }
            (base / "data" / "models.json").write_text(json.dumps(models_payload), encoding="utf-8")
            (base / "config" / "agents_requirements.json").write_text(json.dumps(agents_payload), encoding="utf-8")

            svc = ApplicationService(base)
            server = create_server(svc, port=0)
            port = server.server_address[1]
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                req_failover = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/failover",
                    data=json.dumps({"target": "build", "reason": "rate_limit", "auto_export": True}).encode("utf-8"),
                    headers={"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{port}"},
                    method="POST",
                )
                with urllib.request.urlopen(req_failover, timeout=5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    self.assertTrue(data["ok"])
                    self.assertEqual(len(data["report"]["cooldowns"]), 1)
                    self.assertEqual(
                        data["report"]["assignments"][0]["model"]["id"],
                        "nvidia/nemotron-3-ultra:free",
                    )

                req_clear = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/cooldowns/clear",
                    data=json.dumps({"target_id": "all", "auto_export": True}).encode("utf-8"),
                    headers={"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{port}"},
                    method="POST",
                )
                with urllib.request.urlopen(req_clear, timeout=5) as resp:
                    data_clear = json.loads(resp.read().decode("utf-8"))
                    self.assertTrue(data_clear["ok"])
                    self.assertEqual(len(data_clear["report"]["cooldowns"]), 0)
                    self.assertEqual(
                        data_clear["report"]["assignments"][0]["model"]["id"],
                        "google/gemma-4-31b:free",
                    )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
