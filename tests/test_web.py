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
        self._shutdown_event = threading.Event()

        def _serve() -> None:
            try:
                self.httpd.serve_forever(poll_interval=0.01)
            finally:
                self._shutdown_event.set()

        self.thread = threading.Thread(target=_serve, daemon=True)
        self.thread.start()
        host, port = self.httpd.server_address[:2]
        self.base = f"http://{host}:{port}"

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self._shutdown_event.wait(timeout=2.0)
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
        with patch("src.service.fetch_openrouter_models", side_effect=OSError("offline")):
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

    def test_get_rejects_untrusted_host_header(self) -> None:
        """Les requêtes GET avec un en-tête Host suspect (DNS Rebinding) sont rejetées avec 403."""
        request = urllib.request.Request(
            self.base + "/api/report",
            headers={"Host": "evil.com:8765"},
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(ctx.exception.code, 403)
        ctx.exception.close()

    def test_response_includes_security_headers(self) -> None:
        """Vérifie la présence des en-têtes défensifs de sécurité HTTP."""
        with urllib.request.urlopen(self.base + "/", timeout=5) as response:
            headers = dict(response.headers)
            self.assertEqual(headers.get("X-Frame-Options"), "DENY")
            self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
            self.assertIn("frame-ancestors 'none'", headers.get("Content-Security-Policy", ""))

    def test_post_recalculate_returns_report(self) -> None:
        """Vérifie que POST /api/recalculate renvoie un rapport complet."""
        request = urllib.request.Request(
            self.base + "/api/recalculate",
            data=json.dumps({"fallback": True}).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, 200)
            payload = json.loads(response.read().decode("utf-8"))
            self.assertTrue(payload.get("ok"))
            self.assertIn("report", payload)
            self.assertIn("assignments", payload["report"])

    def test_post_agent_update_valid_and_invalid(self) -> None:
        """Vérifie le comportement de POST /api/agent/update."""
        # 1. Mise à jour valide d'un agent existant
        update_data = {
            "agent_name": "agent",
            "updates": {"prefer_tier1": True, "sort_strategy": "lowest_cost"},
            "fallback": True,
        }
        request = urllib.request.Request(
            self.base + "/api/agent/update",
            data=json.dumps(update_data).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, 200)
            payload = json.loads(response.read().decode("utf-8"))
            self.assertTrue(payload.get("ok"))
            self.assertIn("mises à jour", payload.get("message", ""))

        # 2. Requête invalide (agent_name manquant) -> 400
        bad_request = urllib.request.Request(
            self.base + "/api/agent/update",
            data=json.dumps({"updates": {}}).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(bad_request, timeout=5)
        self.assertEqual(ctx.exception.code, 400)
        ctx.exception.close()

    def test_unknown_path_returns_404(self) -> None:
        """Vérifie qu'un chemin inconnu renvoie une erreur 404."""
        request = urllib.request.Request(
            self.base + "/api/unknown-endpoint",
            data=b"{}",
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(ctx.exception.code, 404)
        ctx.exception.close()

    def test_error_message_sanitizes_absolute_paths(self) -> None:
        """Les chemins internes absolus du serveur sont masqués dans les réponses d'erreur."""
        from src.service import OperationResult

        with patch.object(self.service, "sync_catalogue") as mock_sync:
            internal_path = str(self.service.base_dir.resolve() / "secret_dir" / "file.txt")
            mock_sync.return_value = OperationResult(False, f"Erreur avec le fichier {internal_path}")
            status, payload = self._post("/api/sync")
            self.assertEqual(status, 400)
            self.assertFalse(payload["ok"])
            self.assertNotIn(str(self.service.base_dir.resolve()), payload["message"])
            self.assertIn("./secret_dir/file.txt", payload["message"])


if __name__ == "__main__":
    unittest.main()
