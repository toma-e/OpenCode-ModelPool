"""Tests unitaires pour le connecteur Ollama local."""

import json
import unittest
from unittest.mock import MagicMock, patch

from src.providers.ollama import (
    fetch_ollama_tags,
    get_ollama_models,
    parse_ollama_model,
)


class TestOllamaProvider(unittest.TestCase):
    def test_parse_ollama_model_qwen(self) -> None:
        raw = {"name": "qwen2.5-coder:7b", "size": 4700000000}
        model = parse_ollama_model(raw)
        self.assertIsNotNone(model)
        self.assertEqual(model.id, "ollama/qwen2.5-coder:7b")
        self.assertEqual(model.provider, "ollama")
        self.assertEqual(model.cost_input_per_m, 0.0)
        self.assertEqual(model.cost_output_per_m, 0.0)
        self.assertEqual(model.tier, "free_tier")
        self.assertTrue(model.supports_tools)
        self.assertEqual(model.context_window, 131072)

    def test_parse_ollama_model_deepseek_r1(self) -> None:
        raw = {"name": "deepseek-r1:14b"}
        model = parse_ollama_model(raw)
        self.assertIsNotNone(model)
        self.assertEqual(model.id, "ollama/deepseek-r1:14b")
        self.assertTrue(model.supports_reasoning)

    def test_parse_ollama_model_vision(self) -> None:
        raw = {"name": "llava:13b"}
        model = parse_ollama_model(raw)
        self.assertIsNotNone(model)
        self.assertTrue(model.supports_vision)

    @patch("src.providers.ollama.urllib.request.urlopen")
    def test_get_ollama_models_success(self, mock_urlopen: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "models": [
                {"name": "llama3.2:3b"},
                {"name": "qwen2.5:14b"},
            ]
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        models = get_ollama_models()
        self.assertEqual(len(models), 2)
        self.assertEqual(models[0].id, "ollama/llama3.2:3b")
        self.assertEqual(models[1].id, "ollama/qwen2.5:14b")

    def test_parse_ollama_model_rejects_non_llms(self) -> None:
        """parse_ollama_model rejette les modèles d'embeddings et audio locaux."""
        non_llms = [
            "nomic-embed-text:latest",
            "bge-m3:latest",
            "all-minilm:latest",
            "whisper:latest",
            "bge-large:latest",
        ]
        for name in non_llms:
            with self.subTest(model_name=name):
                self.assertIsNone(parse_ollama_model({"name": name}))

    @patch("src.providers.ollama.urllib.request.urlopen")
    def test_get_ollama_models_excludes_non_llms(self, mock_urlopen: MagicMock) -> None:
        """get_ollama_models filtre automatiquement les modèles non-LLM."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "models": [
                {"name": "llama3.2:3b"},
                {"name": "nomic-embed-text:latest"},
                {"name": "whisper:latest"},
                {"name": "qwen2.5-coder:7b"},
            ]
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        models = get_ollama_models()
        self.assertEqual(len(models), 2)
        self.assertEqual(models[0].id, "ollama/llama3.2:3b")
        self.assertEqual(models[1].id, "ollama/qwen2.5-coder:7b")

    @patch("src.providers.ollama.urllib.request.urlopen", side_effect=OSError("connection refused"))
    def test_get_ollama_models_handles_offline_gracefully(self, mock_urlopen: MagicMock) -> None:
        """Si Ollama n'est pas lancé, la fonction ne lève pas d'exception et renvoie une liste vide."""
        models = get_ollama_models()
        self.assertEqual(models, [])


if __name__ == "__main__":
    unittest.main()

