"""Tests HTTP de l'interface web locale."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from src.service import ApplicationService
from src.web import LISTEN_HOST, create_server
from tests.test_service import write_valid_workspace


class TestWeb(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self._temporary.name)
        write_valid_workspace(self.directory)
        self.service = ApplicationService(self.directory)
        self.httpd = create_server(self.service, port=0)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.httpd.server_address[:2]
        self.base = f"http://{host}:{port}"

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self._temporary.cleanup()

    def _get(self, path: str) -> tuple[int, bytes]:
        with urllib.request.urlopen(self.base + path, timeout=5) as response:
            return response.status, response.read()

    def _post(self, path: str, payload: dict[str, object] | None = None) -> tuple[int, dict[str, object]]:
        body = json.dumps(payload or {}).encode("utf-8")
        request = urllib.request.Request(
            self.base + path,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raw = error.read()
            error.close()
            return error.code, json.loads(raw.decode("utf-8"))

    def test_server_binds_loopback_only(self) -> None:
        self.assertEqual(self.httpd.server_address[0], LISTEN_HOST)

    def test_get_index_and_report(self) -> None:
        status, html = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"ModelScope", html)
        status, raw = self._get("/api/report")
        self.assertEqual(status, 200)
        payload = json.loads(raw.decode("utf-8"))
        self.assertTrue(payload["ok"])
        assignments = payload["report"]["assignments"]
        assert isinstance(assignments, list)
        self.assertEqual(assignments[0]["model"]["id"], "test/model")

    def test_post_sync_error_keeps_catalogue(self) -> None:
        before = self.service.models_path.read_text(encoding="utf-8")
        with patch("src.service.sync_models_from_openrouter", side_effect=OSError("offline")):
            status, payload = self._post("/api/sync")
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertIn("offline", str(payload["message"]))
        self.assertEqual(self.service.models_path.read_text(encoding="utf-8"), before)

    def test_post_export_writes_file(self) -> None:
        status, payload = self._post("/api/export")
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertTrue(self.service.default_export_path.exists())

    def test_post_rejects_untrusted_origin(self) -> None:
        request = urllib.request.Request(
            self.base + "/api/export",
            data=b"{}",
            method="POST",
            headers={"Content-Type": "application/json", "Origin": "https://evil-site.com"},
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(ctx.exception.code, 403)
        ctx.exception.close()

    def test_post_rejects_missing_json_content_type(self) -> None:
        request = urllib.request.Request(
            self.base + "/api/export",
            data=b"{}",
            method="POST",
            headers={"Content-Type": "text/plain"},
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(ctx.exception.code, 415)
        ctx.exception.close()


if __name__ == "__main__":
    unittest.main()
