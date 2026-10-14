"""Tests unitaires pour la détection sécurisée des identifiants et clés API."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.providers.detector import (
    detect_provider_credentials,
    get_available_provider_names,
    is_ollama_reachable,
    load_opencode_auth_keys,
    mask_key,
    parse_dotenv_file,
)


class TestProviderDetector(unittest.TestCase):
    def test_mask_key(self) -> None:
        self.assertIsNone(mask_key(None))
        self.assertIsNone(mask_key(""))
        self.assertEqual(mask_key("short"), "****")
        self.assertEqual(mask_key("sk-ant-api03-123456789"), "sk-a...6789")

    def test_parse_dotenv_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / ".env"
            env_file.write_text(
                "# Commentaire\n"
                "MISTRAL_API_KEY=mis_secret_1234\n"
                "GROQ_API_KEY=\"gsk_custom_value\"\n"
                "EMPTY_VAR=\n",
                encoding="utf-8",
            )
            parsed = parse_dotenv_file(env_file)
            self.assertEqual(parsed.get("MISTRAL_API_KEY"), "mis_secret_1234")
            self.assertEqual(parsed.get("GROQ_API_KEY"), "gsk_custom_value")
            self.assertEqual(parsed.get("EMPTY_VAR"), "")
            self.assertNotIn("COMMENT", parsed)

    def test_load_opencode_auth_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            auth_file = Path(temp_dir) / "auth.json"
            auth_file.write_text(
                json.dumps({
                    "openrouter": {"key": "sk-or-v1-secret"},
                    "anthropic": "sk-ant-secret",
                }),
                encoding="utf-8",
            )
            keys = load_opencode_auth_keys(auth_file)
            self.assertEqual(keys.get("openrouter"), "sk-or-v1-secret")
            self.assertEqual(keys.get("anthropic"), "sk-ant-secret")

    @patch("src.providers.detector.is_ollama_reachable", return_value=True)
    def test_detect_provider_credentials_with_env(self, mock_ollama: object) -> None:
        with patch.dict(os.environ, {"MISTRAL_API_KEY": "mis_12345678", "GROQ_API_KEY": ""}):
            creds = detect_provider_credentials(
                check_ollama=True,
                opencode_auth_path=Path("/non/existent/auth.json"),
            )
            self.assertTrue(creds["mistralai"].is_available)
            self.assertEqual(creds["mistralai"].source, "env")
            self.assertEqual(creds["mistralai"].masked_key, "mis_...5678")

            # Ollama joignable
            self.assertTrue(creds["ollama"].is_available)
            self.assertEqual(creds["ollama"].source, "local_service")

            # Groq non configuré
            self.assertFalse(creds["groq"].is_available)

    def test_get_available_provider_names(self) -> None:
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-12345678"}, clear=True):
            with patch("src.providers.detector.is_ollama_reachable", return_value=False):
                names = get_available_provider_names(
                    allow_unkeyed_openrouter_free=True,
                    opencode_auth_path=Path("/non/existent/auth.json"),
                )
                self.assertIn("anthropic", names)
                self.assertIn("openrouter", names)  # Ouvert pour free
                self.assertNotIn("ollama", names)
                self.assertNotIn("mistralai", names)


if __name__ == "__main__":
    unittest.main()
