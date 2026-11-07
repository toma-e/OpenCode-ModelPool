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
from src.web import (
    LISTEN_HOST,
    LocalInterfaceHandler,
    ModelPoolServer,
    create_server,
    serve_local_interface,
)
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

    def _head(self, path: str, headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
        req_headers = headers or {}
        request = urllib.request.Request(self.base + path, method="HEAD", headers=req_headers)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            raw = error.read()
            resp_headers = dict(error.headers)
            error.close()
            return error.code, resp_headers, raw

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
        self.assertIn(b"OpenCode-ModelPool", html)
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

    def test_post_rejects_untrusted_origin_scheme_and_port(self) -> None:
        """L'origine doit être HTTP et correspondre au port d'écoute."""
        # 1. Scheme HTTPS sur localhost
        req_https = urllib.request.Request(
            self.base + "/api/recalculate",
            data=b"{}",
            method="POST",
            headers={"Content-Type": "application/json", "Origin": "https://127.0.0.1"},
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req_https, timeout=5)
        self.assertEqual(ctx.exception.code, 403)
        ctx.exception.close()

        # 2. Port différent du port serveur
        req_port = urllib.request.Request(
            self.base + "/api/recalculate",
            data=b"{}",
            method="POST",
            headers={"Content-Type": "application/json", "Origin": "http://127.0.0.1:12345"},
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req_port, timeout=5)
        self.assertEqual(ctx.exception.code, 403)
        ctx.exception.close()

    def test_post_export_path_security(self) -> None:
        """Vérifie le rejet de la traversée de répertoire et des chemins hors projet."""
        # Traversée interdite (..)
        status, payload = self._post("/api/export", {"path": "../escaped.json"})
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertIn("traversée", payload["message"].lower())

        # Chemin externe absolu interdit
        status, payload = self._post("/api/export", {"path": "/var/log/forbidden.json"})
        self.assertEqual(status, 403)
        self.assertFalse(payload["ok"])
        self.assertIn("interdit", payload["message"].lower())

        # Fichier sensible ou arbitraire interdit (doit obligatoirement être opencode.json ou opencode.jsonc)
        status, payload = self._post("/api/export", {"path": ".env"})
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertIn("opencode.json", payload["message"].lower())

        # Répertoire interdit
        status, payload = self._post("/api/export", {"path": "config"})
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertIn("répertoire", payload["message"].lower())

    def test_post_diff_path_security(self) -> None:
        """Vérifie que POST /api/diff restreint strictement les chemins pour empêcher la fuite de fichiers."""
        # 1. Traversée interdite (..)
        status, payload = self._post("/api/diff", {"path": "../../etc/passwd"})
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertIn("traversée", payload["message"].lower())

        # 2. Chemin externe absolu interdit
        status, payload = self._post("/api/diff", {"path": "/etc/shadow"})
        self.assertEqual(status, 403)
        self.assertFalse(payload["ok"])
        self.assertIn("interdit", payload["message"].lower())

        # 3. Tentative de lecture de secret interne (.env ou auth.json) via le diff rejetée
        status, payload = self._post("/api/diff", {"path": ".env"})
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertIn("opencode.json", payload["message"].lower())

        # 4. Répertoire interdit
        status, payload = self._post("/api/diff", {"path": "config"})
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertIn("répertoire", payload["message"].lower())

    def test_post_diff_endpoint(self) -> None:
        """Vérifie que POST /api/diff génère la prévisualisation et valide le schéma."""
        status, payload = self._post("/api/diff")
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["is_valid"])
        self.assertIn("diff", payload)

    def test_post_export_global_target(self) -> None:
        """Vérifie que l'alias 'global' est accepté par POST /api/export sans écraser ~/.config."""
        with patch.object(self.service, "export_config", return_value=self.service.export_config(path=self.directory / "fake_global.json")) as mock_export:
            status, payload = self._post("/api/export", {"path": "global"})
            self.assertEqual(status, 200)
            self.assertTrue(payload["ok"])
            mock_export.assert_called_once()
            called_path = mock_export.call_args[1].get("path")
            self.assertTrue(str(called_path).endswith(str(Path(".config") / "opencode" / "opencode.json")))

    def test_post_integrate_endpoint(self) -> None:
        """Vérifie l'endpoint POST /api/integrate vers un répertoire projet temporaire."""
        target_dir = self.directory / "opencode_proj"
        status, payload = self._post("/api/integrate", {"target": "project", "project_path": str(target_dir), "use_symlink": False})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertIn("Intégration OpenCode", payload["message"])

    def test_post_integrate_security_validations(self) -> None:
        """Vérifie que POST /api/integrate rejette les cibles inconnues et les traversées de répertoire."""
        # 1. Cible non autorisée
        status, payload = self._post("/api/integrate", {"target": "malicious_target"})
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertIn("invalide", payload["message"].lower())

        # 2. Traversée de répertoire (..) dans project_path
        status, payload = self._post("/api/integrate", {"target": "project", "project_path": "../escape"})
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertIn("traversée interdite", payload["message"].lower())

        # 3. Chemin absolu hors du projet
        status, payload = self._post("/api/integrate", {"target": "project", "project_path": "/var/run/opencode"})
        self.assertEqual(status, 403)
        self.assertFalse(payload["ok"])
        self.assertIn("interdite en dehors du projet", payload["message"].lower())

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
            self.assertEqual(headers.get("X-Permitted-Cross-Domain-Policies"), "none")
            self.assertEqual(headers.get("Referrer-Policy"), "no-referrer")
            csp = headers.get("Content-Security-Policy", "")
            self.assertIn("frame-ancestors 'none'", csp)
            self.assertIn("object-src 'none'", csp)
            self.assertIn("base-uri 'none'", csp)
            self.assertIn("form-action 'self'", csp)

    def test_get_providers_masks_credentials(self) -> None:
        """Vérifie que l'endpoint GET /api/providers ne divulgue jamais de clé brute et applique le masquage."""
        with urllib.request.urlopen(self.base + "/api/providers", timeout=5) as response:
            self.assertEqual(response.status, 200)
            payload = json.loads(response.read().decode("utf-8"))
            self.assertTrue(payload.get("ok"))
            self.assertIn("providers", payload)
            providers = payload["providers"]
            for prov_name, cred in providers.items():
                masked = cred.get("masked_key")
                if masked is not None:
                    # Ne doit jamais être un token brut ou dépasser le format masqué
                    self.assertTrue(masked.startswith("****") or "..." in masked)

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
            "updates": {"prefer_tier1": True, "sort_strategy": "lowest_cost", "reliability_preference": "prefer_stability"},
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


    def test_priority_get_and_post(self) -> None:
        """Vérifie la consultation et la mise à jour de l'ordre de priorité des fournisseurs."""
        status, data = self._get("/api/priority")
        self.assertEqual(status, 200)
        parsed = json.loads(data.decode("utf-8"))
        self.assertTrue(parsed.get("ok"))
        self.assertIsInstance(parsed.get("priority"), list)

        # Mise à jour avec un nouvel ordre
        new_order = ["mistralai", "ollama", "openrouter"]
        post_status, post_data = self._post("/api/priority", {"priority": new_order})
        self.assertEqual(post_status, 200)
        self.assertTrue(post_data.get("ok"))
        self.assertIn("priorité", post_data.get("message", "").lower())
        self.assertEqual(self.service.get_provider_priority(), new_order)

    def test_models_catalog_get_endpoint(self) -> None:
        """Vérifie la route GET /api/models retournant l'inventaire enrichi du catalogue."""
        status, data = self._get("/api/models")
        self.assertEqual(status, 200)
        parsed = json.loads(data.decode("utf-8"))
        self.assertTrue(parsed.get("ok"))
        self.assertIn("models", parsed)
        self.assertIn("total_models", parsed)
        self.assertIsInstance(parsed["models"], list)
        self.assertGreater(len(parsed["models"]), 0)

        # Contrôle de structure d'un modèle retourné
        first_model = parsed["models"][0]
        self.assertIn("id", first_model)
        self.assertIn("provider", first_model)
        self.assertIn("complexity_score", first_model)
        self.assertIn("supports_tools", first_model)
        self.assertIn("is_executable", first_model)
        self.assertIn("execution_target", first_model)

    def test_get_presets_and_post_add_preset(self) -> None:
        """Vérifie GET /api/presets et POST /api/agent/add-preset."""
        # 1. GET /api/presets
        status, data = self._get("/api/presets")
        self.assertEqual(status, 200)
        parsed = json.loads(data.decode("utf-8"))
        self.assertTrue(parsed.get("ok"))
        self.assertIn("presets", parsed)
        self.assertIn("code_reviewer", parsed["presets"])

        # 2. POST /api/agent/add-preset valide
        post_status, post_data = self._post("/api/agent/add-preset", {
            "preset_id": "code_reviewer",
            "name": "rev_agent",
        })
        self.assertEqual(post_status, 200)
        self.assertTrue(post_data.get("ok"))
        self.assertIn("rev_agent", post_data.get("message", ""))

        # 3. POST avec preset manquant -> 400
        err_status, err_data = self._post("/api/agent/add-preset", {})
        self.assertEqual(err_status, 400)

    def test_diff_section_accessibility_attributes(self) -> None:
        """Vérifie la présence des attributs d'accessibilité ARIA et focus sur la prévisualisation du diff."""
        status, html_bytes = self._get("/")
        self.assertEqual(status, 200)
        html = html_bytes.decode("utf-8")
        self.assertIn('id="diff_section"', html)
        self.assertIn('role="region"', html)
        self.assertIn('aria-labelledby="diff_heading"', html)
        self.assertIn('id="diff_heading"', html)
        self.assertIn('id="close_diff_btn"', html)
        self.assertIn('aria-label="Fermer la prévisualisation du diff"', html)
        self.assertIn('tabindex="0" role="region" aria-label="Contenu du diff unifié"', html)

    def test_head_static_files(self) -> None:
        """Vérifie que HEAD sur / et /index.html renvoie 200, les en-têtes corrects et un corps vide."""
        for path in ("/", "/index.html"):
            status, headers, body = self._head(path)
            self.assertEqual(status, 200)
            self.assertEqual(body, b"")
            self.assertEqual(headers.get("Content-Type"), "text/html; charset=utf-8")
            self.assertEqual(headers.get("Cache-Control"), "no-store")
            self.assertEqual(headers.get("X-Frame-Options"), "DENY")
            self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
            self.assertIn("Content-Length", headers)
            self.assertGreater(int(headers["Content-Length"]), 0)

    def test_head_api_endpoints(self) -> None:
        """Vérifie que HEAD sur /api/report et /api/models renvoie 200, Content-Type JSON, en-têtes de sécurité et corps vide."""
        for path in ("/api/report", "/api/models"):
            status, headers, body = self._head(path)
            self.assertEqual(status, 200)
            self.assertEqual(body, b"")
            self.assertEqual(headers.get("Content-Type"), "application/json; charset=utf-8")
            self.assertEqual(headers.get("Cache-Control"), "no-store")
            self.assertEqual(headers.get("X-Frame-Options"), "DENY")
            self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")

    def test_head_unknown_path_returns_404(self) -> None:
        """Vérifie que HEAD sur un chemin inexistant renvoie 404 avec en-têtes de sécurité et corps vide."""
        status, headers, body = self._head("/api/unknown-endpoint")
        self.assertEqual(status, 404)
        self.assertEqual(body, b"")
        self.assertEqual(headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")

    def test_head_rejects_untrusted_host_header(self) -> None:
        """Vérifie que HEAD avec un en-tête Host suspect est rejeté avec 403 et corps vide."""
        status, headers, body = self._head("/api/report", headers={"Host": "evil.com:8765"})
        self.assertEqual(status, 403)
        self.assertEqual(body, b"")
        self.assertEqual(headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")

    def test_create_server_defaults_and_binding(self) -> None:
        """Vérifie les arguments par défaut de create_server et le couplage du handler."""
        with patch("src.web.ModelPoolServer") as mock_server_cls:
            mock_server_instance = mock_server_cls.return_value
            server = create_server(self.service)

            self.assertIs(server, mock_server_instance)
            mock_server_cls.assert_called_once()
            args, _ = mock_server_cls.call_args
            server_address, handler_cls = args

            self.assertEqual(server_address, (LISTEN_HOST, 8765))
            self.assertTrue(issubclass(handler_cls, LocalInterfaceHandler))
            self.assertIs(handler_cls.service, self.service)
            self.assertTrue(handler_cls.allow_fallback)

    def test_create_server_custom_port_and_fallback(self) -> None:
        """Vérifie create_server avec un port personnalisé et allow_fallback=False."""
        with patch("src.web.ModelPoolServer") as mock_server_cls:
            mock_server_instance = mock_server_cls.return_value
            server = create_server(self.service, port=9000, allow_fallback=False)

            self.assertIs(server, mock_server_instance)
            mock_server_cls.assert_called_once()
            args, _ = mock_server_cls.call_args
            server_address, handler_cls = args

            self.assertEqual(server_address, (LISTEN_HOST, 9000))
            self.assertIs(handler_cls.service, self.service)
            self.assertFalse(handler_cls.allow_fallback)

    def test_create_server_live_ephemeral_port(self) -> None:
        """Vérifie la création réelle d'un ModelPoolServer sur port éphémère (port 0)."""
        server = create_server(self.service, port=0, allow_fallback=True)
        try:
            self.assertIsInstance(server, ModelPoolServer)
            host, port = server.server_address[:2]
            self.assertEqual(host, LISTEN_HOST)
            self.assertGreater(port, 0)
        finally:
            server.server_close()

    def test_model_pool_server_handle_error(self) -> None:
        """Vérifie que ModelPoolServer ignore les déconnexions client et propage les autres erreurs."""
        from unittest.mock import MagicMock

        server = create_server(self.service, port=0)
        dummy_req = MagicMock()
        try:
            with patch("http.server.ThreadingHTTPServer.handle_error") as mock_super_handle_error:
                # 1. BrokenPipeError ignoré
                with patch("sys.exc_info", return_value=(BrokenPipeError, BrokenPipeError(), None)):
                    server.handle_error(dummy_req, ("127.0.0.1", 12345))
                    mock_super_handle_error.assert_not_called()

                # 2. ConnectionResetError ignoré
                with patch("sys.exc_info", return_value=(ConnectionResetError, ConnectionResetError(), None)):
                    server.handle_error(dummy_req, ("127.0.0.1", 12345))
                    mock_super_handle_error.assert_not_called()

                # 3. Exception ordinaire déléguée à super().handle_error
                generic_exc = RuntimeError("unexpected error")
                with patch("sys.exc_info", return_value=(RuntimeError, generic_exc, None)):
                    server.handle_error(dummy_req, ("127.0.0.1", 12345))
                    mock_super_handle_error.assert_called_once_with(dummy_req, ("127.0.0.1", 12345))
        finally:
            server.server_close()

    def test_serve_local_interface_clean_shutdown(self) -> None:
        """Vérifie que serve_local_interface gère KeyboardInterrupt proprement sans lever d'exception."""
        import io
        from contextlib import redirect_stdout

        with patch("src.web.create_server") as mock_create:
            mock_server = mock_create.return_value
            mock_server.__enter__.return_value = mock_server
            mock_server.serve_forever.side_effect = KeyboardInterrupt()

            buf = io.StringIO()
            with redirect_stdout(buf):
                serve_local_interface(self.service, port=9000, allow_fallback=False)

            mock_create.assert_called_once_with(self.service, port=9000, allow_fallback=False)
            mock_server.serve_forever.assert_called_once()
            output = buf.getvalue()
            self.assertIn("Arrêt du serveur local", output)


if __name__ == "__main__":
    unittest.main()
