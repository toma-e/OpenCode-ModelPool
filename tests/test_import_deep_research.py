from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

# Add project root to sys.path to import script with hyphens
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import importlib.util

spec = importlib.util.spec_from_file_location("import_deep_research", BASE_DIR / "import-deep-research.py")
if spec is None or spec.loader is None:
    raise ImportError("Cannot load import-deep-research.py")
import_deep_research = importlib.util.module_from_spec(spec)
spec.loader.exec_module(import_deep_research)

normalize_user_path = import_deep_research.normalize_user_path
prompt_select_file = import_deep_research.prompt_select_file


class TestImportDeepResearch(unittest.TestCase):
    def test_normalize_user_path_posix(self) -> None:
        p = normalize_user_path("/tmp/test_dir/file.json")
        self.assertIsInstance(p, Path)

    def test_normalize_user_path_windows_drive(self) -> None:
        p = normalize_user_path("C:\\Users\\Test\\Downloads\\research.json")
        self.assertEqual(str(p), "/mnt/c/Users/Test/Downloads/research.json")

    def test_normalize_user_path_unc(self) -> None:
        p = normalize_user_path("//wsl.localhost/Ubuntu/home/user/file.json")
        self.assertEqual(str(p), "/home/user/file.json")

    def test_normalize_user_path_tilde(self) -> None:
        p = normalize_user_path("~/Downloads")
        self.assertEqual(p, Path.home() / "Downloads")

    def test_prompt_select_file_scanning(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir).resolve()

            # Create candidate JSON files
            good_json = tmp_path / "valid_research.json"
            good_json.write_text('{"models": []}')

            ignored_models_json = tmp_path / "models.json"
            ignored_models_json.write_text('{}')

            from unittest.mock import patch

            with patch("builtins.input", return_value="1"):
                selected = prompt_select_file(tmp_path)
                self.assertEqual(selected, good_json)


if __name__ == "__main__":
    unittest.main()
