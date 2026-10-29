"""Tests unitaires pour les connecteurs d'API directes (Mistral, Groq, Google, Anthropic, Cerebras)."""

import json
import os
import unittest
from unittest.mock import MagicMock, patch

from src.providers.direct import (
    fetch_anthropic_models,
    fetch_cerebras_models,
    fetch_google_models,
    fetch_groq_models,
    fetch_mistral_models,
)


class TestDirectProviders(unittest.TestCase):
    def test_returns_empty_when_no_key(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(fetch_mistral_models(), [])
            self.assertEqual(fetch_groq_models(), [])
            self.assertEqual(fetch_google_models(), [])
            self.assertEqual(fetch_anthropic_models(), [])
            self.assertEqual(fetch_cerebras_models(), [])

    @patch("src.providers.direct.urllib.request.urlopen")
    def test_fetch_mistral_models(self, mock_urlopen: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "data": [
                {"id": "mistral-large-latest", "max_context_length": 128000},
                {"id": "pixtral-12b-2409", "max_context_length": 128000},
                {"id": "mistral-embed"},  # Doit être ignoré (embedding)
                {"id": "codestral-embed"},  # Doit être ignoré (embedding)
                {"id": "mistral-moderation-2411"},  # Doit être ignoré (modération pure)
            ]
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        models = fetch_mistral_models(api_key="fake-mistral-key")
        self.assertEqual(len(models), 2)
        self.assertEqual(models[0].id, "mistral/mistral-large-latest")
        self.assertEqual(models[0].provider, "mistralai")
        self.assertTrue(models[0].supports_tools)
        self.assertTrue(models[1].supports_vision)

    @patch("src.providers.direct.urllib.request.urlopen")
    def test_fetch_groq_models(self, mock_urlopen: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "data": [
                {"id": "llama-3.3-70b-versatile", "context_window": 128000},
                {"id": "whisper-large-v3"},  # Doit être ignoré (transcription audio)
                {"id": "playht-tts"},  # Doit être ignoré (tts)
            ]
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        models = fetch_groq_models(api_key="fake-groq-key")
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0].id, "groq/llama-3.3-70b-versatile")
        self.assertEqual(models[0].provider, "groq")

    @patch("src.providers.direct.urllib.request.urlopen")
    def test_fetch_google_models(self, mock_urlopen: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "models": [
                {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"], "inputTokenLimit": 1000000},
                {"name": "models/gemini-2.5-pro", "supportedGenerationMethods": ["generateContent"], "inputTokenLimit": 1000000},
                {"name": "models/lyria-3-clip-preview", "supportedGenerationMethods": ["generateContent"]},  # Doit être ignoré (musique)
                {"name": "models/imagen-3.0-generate-002", "supportedGenerationMethods": ["generateContent"]},  # Doit être ignoré (image)
                {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]},  # Doit être ignoré (embedding)
                {"name": "models/aqa", "supportedGenerationMethods": ["generateAnswer"]},  # Doit être ignoré
            ]
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        models = fetch_google_models(api_key="fake-google-key")
        self.assertEqual(len(models), 2)
        self.assertEqual(models[0].id, "google/gemini-2.5-flash")
        self.assertEqual(models[1].id, "google/gemini-2.5-pro")
        self.assertEqual(models[0].provider, "google")

        # Vérifier que l'URL ne contient pas la clé et que l'en-tête x-goog-api-key est présent
        req = mock_urlopen.call_args[0][0]
        self.assertNotIn("key=", req.full_url)
        self.assertEqual(req.headers.get("X-goog-api-key"), "fake-google-key")

    @patch("src.providers.direct.urllib.request.urlopen")
    def test_fetch_anthropic_models(self, mock_urlopen: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "data": [
                {"id": "claude-3-5-sonnet-latest"},
            ]
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        models = fetch_anthropic_models(api_key="fake-ant-key")
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0].id, "anthropic/claude-3-5-sonnet-latest")
        self.assertEqual(models[0].provider, "anthropic")
        self.assertEqual(models[0].complexity_score, 5)
        self.assertTrue(models[0].supports_tools)


if __name__ == "__main__":
    unittest.main()

