"""Tests unitaires pour la synchronisation multi-fournisseurs consolidée."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.fetcher import sync_models_from_all_providers
from src.selector import Model


class TestMultiSync(unittest.TestCase):
    @patch("src.fetcher.fetch_openrouter_models")
    @patch("src.providers.ollama.fetch_ollama_tags")
    @patch("src.providers.detector.is_ollama_reachable", return_value=True)
    def test_sync_all_providers_consolidates(
        self,
        mock_ollama_reach: MagicMock,
        mock_ollama_tags: MagicMock,
        mock_openrouter: MagicMock,
    ) -> None:
        mock_openrouter.return_value = [
            {
                "id": "meta-llama/llama-3.3-70b-instruct",
                "pricing": {"prompt": "0.000001", "completion": "0.000002"},
                "context_length": 131072,
                "supported_parameters": ["tools"],
            }
        ]
        mock_ollama_tags.return_value = [
            {"name": "qwen2.5-coder:7b"}
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "models.json"
            no_auth = Path(temp_dir) / "empty_auth.json"
            total, backup, summary = sync_models_from_all_providers(
                out_path,
                include_openrouter=True,
                include_ollama=True,
                create_backup_file=False,
                opencode_auth_path=no_auth,
            )

            self.assertEqual(total, 2)
            self.assertEqual(summary.get("openrouter"), 1)
            self.assertEqual(summary.get("ollama"), 1)

            saved_data = json.loads(out_path.read_text(encoding="utf-8"))
            ids = [m["id"] for m in saved_data["models"]]
            self.assertIn("meta-llama/llama-3.3-70b-instruct", ids)
            self.assertIn("ollama/qwen2.5-coder:7b", ids)


if __name__ == "__main__":
    unittest.main()
