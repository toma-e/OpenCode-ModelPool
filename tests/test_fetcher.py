"""Tests unitaires pour le module de synchronisation et de backup fetcher.py."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import URLError

from src.fetcher import (
    create_backup,
    estimate_complexity_score,
    fetch_openrouter_models,
    parse_openrouter_model,
    prune_timestamped_backups,
    sync_models_from_openrouter,
    write_json_atomic,
)


class TestFetcher(unittest.TestCase):
    def test_estimate_complexity_score(self) -> None:
        self.assertEqual(estimate_complexity_score("anthropic/claude-3-5-sonnet", 3.0), 5)
        self.assertEqual(estimate_complexity_score("deepseek/deepseek-r1", 0.55), 5)
        self.assertEqual(estimate_complexity_score("meta-llama/llama-3.3-70b-instruct", 0.12), 4)
        self.assertEqual(estimate_complexity_score("mistralai/mistral-large-2407", 2.0), 4)
        self.assertEqual(estimate_complexity_score("google/gemini-2.5-flash", 0.0), 3)
        self.assertEqual(estimate_complexity_score("google/gemini-2.5-flash-lite", 0.0), 2)
        self.assertEqual(estimate_complexity_score("meta-llama/llama-3.2-1b-instruct", 0.0), 1)
        self.assertEqual(estimate_complexity_score("google/gemma-4-31b-it", 0.0), 3)
        self.assertEqual(estimate_complexity_score("qwen/qwen3.6-35b-a3b", 0.0), 4)
        self.assertEqual(estimate_complexity_score("microsoft/wizardlm-2-8x22b", 0.0), 4)
        # Cas réels o-series et nano/mini
        self.assertEqual(estimate_complexity_score("openai/o4-mini", 0.0), 3)
        self.assertEqual(estimate_complexity_score("openai/o4-mini-high", 0.0), 4)
        self.assertEqual(estimate_complexity_score("openai/o1-mini", 0.0), 3)
        self.assertEqual(estimate_complexity_score("openai/o1", 0.0), 5)
        self.assertEqual(estimate_complexity_score("openai/gpt-5-nano", 0.0), 1)
        self.assertEqual(estimate_complexity_score("openai/gpt-4.1-nano", 0.0), 1)
        self.assertEqual(estimate_complexity_score("sao10k/l3-lunaris-8b", 0.0), 3)
        self.assertEqual(estimate_complexity_score("upstage/solar-pro4", 0.0), 3)

    @patch("src.fetcher.urllib.request.urlopen", side_effect=URLError("timeout"))
    def test_fetch_openrouter_models_propagates_network_error(self, mocked_urlopen: object) -> None:
        """Une erreur réseau n'est pas transformée en catalogue vide."""
        with self.assertRaises(URLError):
            fetch_openrouter_models(timeout=1)

    def test_parse_openrouter_model_valid(self) -> None:
        raw = {
            "id": "anthropic/claude-3-5-sonnet",
            "pricing": {"prompt": "0.000003", "completion": "0.000015"},
            "context_length": 200000,
            "supported_parameters": ["tools", "temperature"],
        }
        model = parse_openrouter_model(raw)
        self.assertIsNotNone(model)
        assert model is not None
        self.assertEqual(model.id, "anthropic/claude-3-5-sonnet")
        self.assertEqual(model.provider, "anthropic")
        self.assertEqual(model.cost_input_per_m, 3.0)
        self.assertEqual(model.cost_output_per_m, 15.0)
        self.assertTrue(model.supports_tools)
        self.assertEqual(model.tier, "pay_as_you_go")
        self.assertEqual(model.complexity_score, 5)
        self.assertTrue(model.supports_vision)
        self.assertFalse(model.supports_reasoning)

    def test_parse_openrouter_model_reasoning_and_vision_modalities(self) -> None:
        raw_r1 = {
            "id": "deepseek/deepseek-r1",
            "pricing": {"prompt": "0.00000055", "completion": "0.00000219"},
            "context_length": 128000,
            "supported_parameters": ["tools"],
            "architecture": {"modality": "text->text"},
        }
        model_r1 = parse_openrouter_model(raw_r1)
        self.assertIsNotNone(model_r1)
        assert model_r1 is not None
        self.assertTrue(model_r1.supports_reasoning)
        self.assertFalse(model_r1.supports_vision)

        raw_vl = {
            "id": "qwen/qwen-2.5-vl-72b-instruct",
            "pricing": {"prompt": "0.0000004", "completion": "0.0000004"},
            "context_length": 128000,
            "supported_parameters": ["tools"],
            "architecture": {"modality": "text+image->text"},
            "input_modalities": ["text", "image"],
        }
        model_vl = parse_openrouter_model(raw_vl)
        self.assertIsNotNone(model_vl)
        assert model_vl is not None
        self.assertTrue(model_vl.supports_vision)
        self.assertFalse(model_vl.supports_reasoning)

        # Modèle avec reasoning objet et vision dans architecture.input_modalities
        raw_sonnet = {
            "id": "anthropic/claude-sonnet-5.5",
            "pricing": {"prompt": "0.000002", "completion": "0.00001"},
            "context_length": 200000,
            "supported_parameters": ["tools"],
            "architecture": {
                "modality": "text+image->text",
                "input_modalities": ["text", "image", "file"],
            },
            "reasoning": {"mandatory": True, "supported_efforts": ["high", "low"]},
        }
        model_sonnet = parse_openrouter_model(raw_sonnet)
        self.assertIsNotNone(model_sonnet)
        assert model_sonnet is not None
        self.assertTrue(model_sonnet.supports_vision)
        self.assertTrue(model_sonnet.supports_reasoning)

    def test_parse_openrouter_model_free(self) -> None:
        raw = {
            "id": "google/gemma-3-12b-it:free",
            "pricing": {"prompt": "0.0", "completion": "0.0"},
            "context_length": 131072,
            "supported_parameters": ["tools"],
        }
        model = parse_openrouter_model(raw)
        self.assertIsNotNone(model)
        assert model is not None
        self.assertEqual(model.tier, "free_tier")
        self.assertEqual(model.cost_input_per_m, 0.0)

    def test_parse_openrouter_model_negative_price_filtered(self) -> None:
        raw = {
            "id": "dummy/router",
            "pricing": {"prompt": "-1.0", "completion": "-1.0"},
            "context_length": 4096,
        }
        self.assertIsNone(parse_openrouter_model(raw))

    def test_create_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            target = tmp_path / "models.json"
            target.write_text(json.dumps({"test": "data"}), encoding="utf-8")

            bkp_timestamp, bkp_bak = create_backup(target)

            self.assertIsNotNone(bkp_timestamp)
            self.assertIsNotNone(bkp_bak)
            assert bkp_timestamp is not None
            assert bkp_bak is not None
            self.assertTrue(bkp_timestamp.exists())
            self.assertTrue(bkp_bak.exists())
            self.assertEqual(bkp_timestamp.read_text(encoding="utf-8"), json.dumps({"test": "data"}))
            self.assertEqual(bkp_bak.read_text(encoding="utf-8"), json.dumps({"test": "data"}))

    def test_write_json_atomic_replaces_target_without_leaving_temp_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / "models.json"
            target.write_text("{}", encoding="utf-8")
            write_json_atomic(target, {"ok": True, "count": 2})
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"ok": True, "count": 2})
            self.assertEqual(list(Path(tmp_dir).glob("*.tmp")), [])

    def test_write_json_atomic_preserves_previous_file_when_dump_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / "models.json"
            target.write_text(json.dumps({"keep": True}), encoding="utf-8")
            with patch("src.fetcher.json.dump", side_effect=OSError("disque plein")):
                with self.assertRaises(OSError):
                    write_json_atomic(target, {"keep": False})
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"keep": True})

    def test_prune_timestamped_backups_keeps_newest_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            backup_dir = Path(tmp_dir) / "backups"
            backup_dir.mkdir()
            for day in range(5):
                (backup_dir / f"models_2026010{day}_000000.json").write_text("{}", encoding="utf-8")
            prune_timestamped_backups(backup_dir, "models", ".json", keep=3)
            remaining = sorted(path.name for path in backup_dir.iterdir())
            self.assertEqual(
                remaining,
                [
                    "models_20260102_000000.json",
                    "models_20260103_000000.json",
                    "models_20260104_000000.json",
                ],
            )

    def test_parse_openrouter_model_malformed_inputs(self) -> None:
        self.assertIsNone(parse_openrouter_model("not a dict"))  # type: ignore[arg-type]
        self.assertIsNone(parse_openrouter_model({}))
        self.assertIsNone(parse_openrouter_model({"id": ""}))
        self.assertIsNone(parse_openrouter_model({"id": 123}))  # type: ignore[dict-item]

        # Cas pricing non-dict et context_length non-int
        model = parse_openrouter_model({"id": "vendor/fallback", "pricing": None, "context_length": "invalid"})
        self.assertIsNotNone(model)
        assert model is not None
        self.assertEqual(model.cost_input_per_m, 0.0)
        self.assertEqual(model.context_window, 4096)

    def test_estimate_complexity_score_pricing_fallbacks(self) -> None:
        # Modèles inconnus sans mots-clés ni tailles identifiables, s'appuyant sur le tarif
        self.assertEqual(estimate_complexity_score("custom/unknown-model", 2.5), 5)
        self.assertEqual(estimate_complexity_score("custom/unknown-model", 0.8), 4)
        self.assertEqual(estimate_complexity_score("custom/unknown-model", 0.08), 3)
        self.assertEqual(estimate_complexity_score("custom/unknown-model", 0.01), 2)
        self.assertEqual(estimate_complexity_score("custom/unknown-model", 0.0), 3)

    def test_sync_models_from_openrouter_enforces_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / "models.json"
            fake_models = [{"id": f"test/m{i}", "pricing": {"prompt": "0"}} for i in range(3)]
            with patch("src.fetcher.fetch_openrouter_models", return_value=fake_models):
                with self.assertRaises(ValueError) as ctx:
                    sync_models_from_openrouter(target, min_models_threshold=5)
                self.assertIn("Catalogue OpenRouter anormalement réduit", str(ctx.exception))

    def test_sync_models_from_openrouter_full_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / "models.json"
            target.write_text(json.dumps({"models": []}), encoding="utf-8")
            fake_models = [
                {
                    "id": f"provider/model-{i}",
                    "pricing": {"prompt": "0.000001", "completion": "0.000002"},
                    "context_length": 8192,
                    "supported_parameters": ["tools"],
                }
                for i in range(12)
            ]
            fake_models.append({
                "id": "provider/batch-model:batch",
                "pricing": {"prompt": "0.000001"},
            })

            with patch("src.fetcher.fetch_openrouter_models", return_value=fake_models):
                count, backup_path = sync_models_from_openrouter(target, min_models_threshold=5, exclude_batch=True)
                self.assertEqual(count, 12)
                self.assertIsNotNone(backup_path)
                assert backup_path is not None
                self.assertTrue(backup_path.exists())
                saved = json.loads(target.read_text(encoding="utf-8"))
                self.assertEqual(saved["total_models"], 12)
                self.assertEqual(len(saved["models"]), 12)
                # Vérifier que le modèle :batch a bien été exclu
                self.assertFalse(any(":batch" in m["id"] for m in saved["models"]))

    def test_fetch_openrouter_models_payload_validation(self) -> None:
        # Réponse non-dict ou sans liste data
        fake_response_non_dict = MagicMock()
        fake_response_non_dict.__enter__.return_value = fake_response_non_dict
        fake_response_non_dict.read.return_value = b'["not", "a", "dict"]'
        with patch("src.fetcher.urllib.request.urlopen", return_value=fake_response_non_dict):
            with self.assertRaises(ValueError) as ctx:
                fetch_openrouter_models()
            self.assertIn("liste 'data' absente", str(ctx.exception))

        # Réponse avec taille excédant la limite
        fake_large_response = MagicMock()
        fake_large_response.__enter__.return_value = fake_large_response
        fake_large_response.read.return_value = b"x" * 100
        with patch("src.fetcher.urllib.request.urlopen", return_value=fake_large_response):
            with self.assertRaises(ValueError) as ctx:
                fetch_openrouter_models(max_bytes=50)
            self.assertIn("trop volumineuse", str(ctx.exception))

        # Réponse valide contenant un élément non-dict ignoré
        fake_valid_response = MagicMock()
        fake_valid_response.__enter__.return_value = fake_valid_response
        fake_valid_response.read.return_value = json.dumps({
            "data": [{"id": "m1"}, "corrupted_item", {"id": "m2"}]
        }).encode("utf-8")
        with patch("src.fetcher.urllib.request.urlopen", return_value=fake_valid_response):
            models = fetch_openrouter_models()
            self.assertEqual(len(models), 2)
            self.assertEqual(models[0]["id"], "m1")
            self.assertEqual(models[1]["id"], "m2")

    def test_parse_openrouter_model_edge_conditions(self) -> None:
        # Prompt négatif
        self.assertIsNone(parse_openrouter_model({"id": "m", "pricing": {"prompt": "-0.1"}}))
        # Completion négatif
        self.assertIsNone(parse_openrouter_model({"id": "m", "pricing": {"completion": "-0.1"}}))
        # Context length <= 0
        model = parse_openrouter_model({"id": "m", "context_length": 0})
        self.assertIsNotNone(model)
        assert model is not None
        self.assertEqual(model.context_window, 4096)
        # Exception ValueError depuis Model constructor
        with patch("src.fetcher.Model", side_effect=ValueError("bad model")):
            self.assertIsNone(parse_openrouter_model({"id": "m"}))


if __name__ == "__main__":
    unittest.main()
