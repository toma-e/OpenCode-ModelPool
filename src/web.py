"""Serveur HTTP local (127.0.0.1) pour consulter et piloter OpenCode-ModelPool."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import parse_qs, urlparse

from src.service import ApplicationService, OperationResult, serialize_report

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
LISTEN_HOST = "127.0.0.1"


class LocalInterfaceHandler(BaseHTTPRequestHandler):
    """Routes HTTP de l'interface locale ; aucun bind hors de la boucle locale."""

    service: ClassVar[ApplicationService]
    allow_fallback: ClassVar[bool]

    def log_message(self, format: str, *args: object) -> None:
        return

    MAX_POST_BODY_BYTES: ClassVar[int] = 1_000_000

    def _has_safe_host(self) -> bool:
        """Vérifie que l'en-tête Host cible exclusivement l'adresse locale (protection DNS Rebinding)."""
        host = self.headers.get("Host", "").split(":")[0].strip().lower()
        return host in {"127.0.0.1", "localhost"}

    def _is_safe_origin(self) -> bool:
        """Vérifie que la requête provient bien d'une origine locale (protection CSRF/rebinding)."""
        if not self._has_safe_host():
            return False
        origin = self.headers.get("Origin")
        if origin:
            parsed_origin = urlparse(origin)
            origin_host = (parsed_origin.hostname or "").lower()
            if origin_host not in {"127.0.0.1", "localhost"}:
                return False
        return True

    def _send_security_headers(self) -> None:
        """Injecte les en-têtes HTTP de sécurité défensifs contre le Clickjacking et le sniffing MIME."""
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'; default-src 'self' 'unsafe-inline';")

    def do_HEAD(self) -> None:
        if not self._has_safe_host():
            self.send_response(403)
            self._send_security_headers()
            self.end_headers()
            return

        parsed = urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            self._send_static("index.html", "text/html; charset=utf-8", head_only=True)
            return
        if parsed.path == "/api/report":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self._send_security_headers()
            self.end_headers()
            return
        self.send_response(404)
        self._send_security_headers()
        self.end_headers()

    def do_GET(self) -> None:
        if not self._has_safe_host():
            self._send_json(403, {"ok": False, "message": "Accès refusé : en-tête Host non autorisé."})
            return

        parsed = urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            self._send_static("index.html", "text/html; charset=utf-8")
            return
        if parsed.path == "/api/report":
            fallback = _query_fallback(parsed.query, self.allow_fallback)
            filter_keys = _query_bool(parsed.query, "filter_keys", False)
            self._send_operation(self.service.build_report_result(allow_fallback=fallback, filter_by_keys=filter_keys))
            return
        if parsed.path == "/api/providers":
            creds = self.service.get_providers_status()
            payload = {
                "ok": True,
                "providers": {
                    prov: {
                        "is_available": c.is_available,
                        "source": c.source,
                        "masked_key": c.masked_key,
                    }
                    for prov, c in creds.items()
                }
            }
            self._send_json(200, payload)
            return
        if parsed.path == "/api/priority":
            self._send_json(200, {"ok": True, "priority": self.service.get_provider_priority()})
            return
        self._send_json(404, {"ok": False, "message": "Ressource introuvable."})

    def do_POST(self) -> None:
        if not self._is_safe_origin():
            self._send_json(403, {"ok": False, "message": "Accès refusé : origine ou hôte non autorisé."})
            return

        content_type = self.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            self._send_json(415, {"ok": False, "message": "Content-Type doit être 'application/json'."})
            return

        parsed = urlparse(self.path)
        body = self._read_json_body()
        fallback = self.allow_fallback
        filter_keys = False
        custom_priority = None
        if isinstance(body, dict):
            if "fallback" in body and isinstance(body["fallback"], bool):
                fallback = body["fallback"]
            if "filter_keys" in body and isinstance(body["filter_keys"], bool):
                filter_keys = body["filter_keys"]
            if "priority" in body and isinstance(body["priority"], list):
                custom_priority = body["priority"]

        if parsed.path == "/api/recalculate":
            self._send_operation(self.service.build_report_result(allow_fallback=fallback, filter_by_keys=filter_keys, custom_priority=custom_priority))
            return
        if parsed.path == "/api/priority":
            if not isinstance(body, dict) or "priority" not in body or not isinstance(body["priority"], list):
                self._send_json(400, {"ok": False, "message": "Liste 'priority' attendue dans le corps JSON."})
                return
            self._send_operation(self.service.set_provider_priority(body["priority"], allow_fallback=fallback, filter_by_keys=filter_keys))
            return
        if parsed.path == "/api/export":
            self._send_operation(self.service.export_config(allow_fallback=fallback, filter_by_keys=filter_keys, custom_priority=custom_priority))
            return
        if parsed.path == "/api/sync":
            multi_provider = False
            if isinstance(body, dict) and "multi_provider" in body and isinstance(body["multi_provider"], bool):
                multi_provider = body["multi_provider"]
            self._send_operation(
                self.service.sync_catalogue(
                    allow_fallback=fallback,
                    multi_provider=multi_provider,
                    filter_by_keys=filter_keys,
                )
            )
            return
        if parsed.path == "/api/refresh-access":
            self._send_operation(self.service.refresh_provider_access(allow_fallback=fallback))
            return
        if parsed.path == "/api/agent/update":
            if not isinstance(body, dict):
                self._send_json(400, {"ok": False, "message": "Corps JSON attendu."})
                return
            agent_name = body.get("agent_name")
            updates = body.get("updates")
            if not isinstance(agent_name, str) or not isinstance(updates, dict):
                self._send_json(400, {"ok": False, "message": "Champs 'agent_name' (str) et 'updates' (dict) obligatoires."})
                return
            self._send_operation(self.service.update_agent_requirement(agent_name, updates, allow_fallback=fallback))
            return
        self._send_json(404, {"ok": False, "message": "Ressource introuvable."})

    def _read_json_body(self) -> Any:
        length_header = self.headers.get("Content-Length", "0")
        try:
            length = int(length_header)
        except ValueError:
            return None
        if length <= 0 or length > self.MAX_POST_BODY_BYTES:
            return None
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None

    def _read_fallback_from_body(self, default: bool) -> bool:
        body = self._read_json_body()
        if isinstance(body, dict) and "fallback" in body and isinstance(body["fallback"], bool):
            return body["fallback"]
        return default

    def _sanitize_message(self, message: str) -> str:
        """Supprime les chemins absolus internes du serveur dans les messages d'erreur HTTP."""
        if not message:
            return message
        base_str = str(self.service.base_dir.resolve())
        if base_str in message:
            message = message.replace(base_str, ".")
        return message

    def _send_operation(self, result: OperationResult) -> None:
        sanitized_msg = self._sanitize_message(result.message)
        payload: dict[str, Any] = {"ok": result.ok, "message": sanitized_msg}
        if result.report is not None:
            payload["report"] = serialize_report(result.report)
        status = 200 if result.ok else 400
        self._send_json(status, payload)

    def _send_static(self, filename: str, content_type: str, head_only: bool = False) -> None:
        target = (WEB_DIR / filename).resolve()
        if not target.is_relative_to(WEB_DIR.resolve()) or not target.is_file():
            self._send_json(404, {"ok": False, "message": "Page introuvable."})
            return
        body = target.read_bytes()
        try:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self._send_security_headers()
            self.end_headers()
            if not head_only:
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self._send_security_headers()
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass


def _query_bool(query: str, key: str, default: bool) -> bool:
    values = parse_qs(query).get(key, [])
    if not values:
        return default
    token = values[0].strip().lower()
    if token in {"0", "false", "no"}:
        return False
    if token in {"1", "true", "yes"}:
        return True
    return default


def _query_fallback(query: str, default: bool) -> bool:
    return _query_bool(query, "fallback", default)


def make_handler(service: ApplicationService, allow_fallback: bool = True) -> type[LocalInterfaceHandler]:
    """Construit une classe de handler liée au service applicatif."""

    return type(
        "BoundLocalInterfaceHandler",
        (LocalInterfaceHandler,),
        {"service": service, "allow_fallback": allow_fallback},
    )


class ModelPoolServer(ThreadingHTTPServer):
    """Serveur HTTP multithread filtrant les déconnexions client inoffensives."""

    def handle_error(self, request: Any, client_address: Any) -> None:
        import sys
        _cls, exc, _tb = sys.exc_info()
        if isinstance(exc, (BrokenPipeError, ConnectionResetError)):
            return
        super().handle_error(request, client_address)


def create_server(
    service: ApplicationService,
    port: int = 8765,
    allow_fallback: bool = True,
) -> ThreadingHTTPServer:
    """Instancie le serveur lié exclusivement à 127.0.0.1."""
    handler = make_handler(service, allow_fallback=allow_fallback)
    return ModelPoolServer((LISTEN_HOST, port), handler)


def serve_local_interface(
    service: ApplicationService,
    port: int = 8765,
    allow_fallback: bool = True,
) -> None:
    """Démarre le serveur local jusqu'à interruption clavier sans traceback brute."""
    try:
        with create_server(service, port=port, allow_fallback=allow_fallback) as httpd:
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Arrêt du serveur local.")
