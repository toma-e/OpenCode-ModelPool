"""Serveur Model Context Protocol (MCP) natif pour OpenCode-ModelPool.

Ce module implémente un serveur MCP standardisé (version 2024-11-05) au-dessus de JSON-RPC 2.0
via l'entrée/sortie standard (stdio). Il permet aux agents d'OpenCode (build, plan, explore, general)
d'interagir directement avec ModelPool pour :
  1. Consulter le statut des modèles et le budget (modelpool_status).
  2. Ajuster à la volée la stratégie d'un agent (modelpool_switch_strategy).
  3. Signaler un incident ou quota saturé et déclencher un repli immédiat (modelpool_report_issue).
  4. Interroger le catalogue des modèles disponibles (modelpool_list_models).

Zéro dépendance externe (bibliothèque standard Python 3.11+).
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, List, Optional, TextIO

from src.service import ApplicationService


PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "opencode-modelpool"
SERVER_VERSION = "0.3.0"

TOOLS_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "name": "modelpool_status",
        "description": (
            "Retourne le statut d'attribution des agents OpenCode (modèles actifs, canaux, "
            "coûts mensuels prévisionnels, alertes de quotas et mises en quarantaine)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "modelpool_switch_strategy",
        "description": (
            "Modifie les exigences ou force un modèle pour un agent OpenCode (ex: build, plan, "
            "explore, general) et ré-exporte automatiquement la configuration."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_name": {
                    "type": "string",
                    "description": "Nom de l'agent cible (ex: 'build', 'plan', 'explore', 'general').",
                },
                "prefer_free": {
                    "type": "boolean",
                    "description": "Prioriser les modèles gratuits pour cet agent.",
                },
                "reliability_preference": {
                    "type": "string",
                    "enum": ["prefer_free", "balanced", "prefer_stability"],
                    "description": "Arbitrage entre gratuité et stabilité.",
                },
                "force_model": {
                    "type": "string",
                    "description": "Identifiant exact d'un modèle à forcer (ou chaîne vide pour réinitialiser).",
                },
            },
            "required": ["agent_name"],
        },
    },
    {
        "name": "modelpool_report_issue",
        "description": (
            "Signale une erreur (429 rate limit, quota saturé, timeout 503/504) sur un modèle "
            "ou agent, le place en quarantaine et bascule immédiatement sur le modèle de repli."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "target_or_agent": {
                    "type": "string",
                    "description": "Nom de l'agent (ex: 'build') ou identifiant du modèle défaillant.",
                },
                "reason": {
                    "type": "string",
                    "enum": [
                        "rate_limit",
                        "quota_exceeded",
                        "service_unavailable",
                        "insufficient_credits",
                        "other",
                    ],
                    "description": "Raison de l'incident (défaut 'rate_limit').",
                },
                "cooldown_minutes": {
                    "type": "integer",
                    "description": "Durée de la mise en quarantaine en minutes (défaut: 15).",
                },
            },
            "required": ["target_or_agent"],
        },
    },
    {
        "name": "modelpool_list_models",
        "description": (
            "Recherche et liste les modèles disponibles dans le catalogue ModelPool avec leurs scores, "
            "contextes et tarifs."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Terme de recherche dans l'ID ou le nom du modèle.",
                },
                "only_free": {
                    "type": "boolean",
                    "description": "Ne renvoyer que les modèles gratuits ($0/token).",
                },
                "requires_tools": {
                    "type": "boolean",
                    "description": "Filtrer les modèles supportant l'appel d'outils (tool call).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Nombre maximal de résultats à renvoyer (défaut: 10, max: 50).",
                },
            },
        },
    },
]


class ModelPoolMCPServer:
    """Serveur MCP stdio pour OpenCode-ModelPool."""

    def __init__(self, service: ApplicationService) -> None:
        self.service = service

    def handle_request(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Traite une requête JSON-RPC 2.0 et renvoie la réponse correspondante."""
        if not isinstance(request, dict):
            return {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32600, "message": "Requête invalide : doit être un objet JSON."},
            }

        req_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})

        # Gestion des notifications (sans req_id)
        if req_id is None:
            if method in ("notifications/initialized", "initialized"):
                return None
            return None

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {
                        "tools": {
                            "listChanged": False,
                        },
                    },
                    "serverInfo": {
                        "name": SERVER_NAME,
                        "version": SERVER_VERSION,
                    },
                },
            }

        if method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": TOOLS_DEFINITIONS},
            }

        if method == "tools/call":
            tool_name = params.get("name") if isinstance(params, dict) else None
            arguments = params.get("arguments", {}) if isinstance(params, dict) else {}
            return self._execute_tool(req_id, tool_name, arguments)

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": -32601,
                "message": f"Méthode MCP non supportée : '{method}'",
            },
        }

    def _execute_tool(
        self, req_id: Any, tool_name: Optional[str], arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Exécute un outil spécifique et formate la réponse MCP."""
        try:
            if tool_name == "modelpool_status":
                text = self._tool_status()
            elif tool_name == "modelpool_switch_strategy":
                text = self._tool_switch_strategy(arguments)
            elif tool_name == "modelpool_report_issue":
                text = self._tool_report_issue(arguments)
            elif tool_name == "modelpool_list_models":
                text = self._tool_list_models(arguments)
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32602,
                        "message": f"Outil inconnu : '{tool_name}'",
                    },
                }

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": text}],
                    "isError": False,
                },
            }
        except Exception as error:  # pylint: disable=broad-except
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"Erreur lors de l'exécution de '{tool_name}' : {error}"}],
                    "isError": True,
                },
            }

    def _tool_status(self) -> str:
        report = self.service.build_report(allow_fallback=True)
        lines: List[str] = [
            f"=== Statut OpenCode-ModelPool (v{SERVER_VERSION}) ===",
            f"Coût mensuel estimé de la flotte : ${report.budget.total_monthly_cost:.4f}",
            f"Volume mensuel estimé : {report.budget.total_tokens:,} tokens",
            "",
            "Attributions par agent :",
        ]
        for res, target in zip(report.results, list(report.execution_targets) + [None] * len(report.results)):
            target_str = target.description_label if target else "Direct"
            model_id = res.model.id if res.model else "Aucun modèle"
            status_tag = "[FALLBACK]" if res.is_fallback else "[EXACT]"
            lines.append(f"  • {res.agent_name:<10} : {model_id} ({status_tag}, Canal: {target_str})")

        if report.diagnostics:
            lines.append("\nDiagnostics & Avertissements :")
            for diag in report.diagnostics:
                lines.append(f"  ⚠️ {diag}")

        cooldowns = self.service.get_active_cooldowns()
        if cooldowns:
            lines.append("\nModèles en quarantaine (Cooldowns) :")
            for cd in cooldowns:
                lines.append(f"  ⏳ {cd.target_id} ({cd.reason}) jusqu'à {cd.expires_at}")

        return "\n".join(lines)

    def _tool_switch_strategy(self, args: Dict[str, Any]) -> str:
        agent_name = args.get("agent_name")
        if not agent_name:
            raise ValueError("L'argument 'agent_name' est obligatoire.")

        patch: Dict[str, Any] = {}
        if "prefer_free" in args:
            patch["prefer_free"] = bool(args["prefer_free"])
        if "reliability_preference" in args:
            patch["reliability_preference"] = str(args["reliability_preference"])
        if "force_model" in args:
            force_val = args["force_model"]
            patch["force_model"] = force_val if force_val else None

        res = self.service.update_agent_requirement(
            agent_name,
            patch,
            allow_fallback=True,
        )
        if not res.ok:
            raise ValueError(res.message)

        # Ré-export automatique vers opencode.json
        self.service.export_config(allow_fallback=True)

        return (
            f"✅ Stratégie de l'agent '{agent_name}' mise à jour.\n"
            f"Résultat : {res.message}\n"
            f"La configuration OpenCode a été automatiquement ré-exportée."
        )

    def _tool_report_issue(self, args: Dict[str, Any]) -> str:
        target = args.get("target_or_agent")
        if not target:
            raise ValueError("L'argument 'target_or_agent' est obligatoire.")
        reason = args.get("reason", "rate_limit")
        cooldown_min = args.get("cooldown_minutes")
        duration_sec = cooldown_min * 60 if cooldown_min else None

        res = self.service.report_model_error(
            target_or_agent=target,
            reason=reason,
            duration_seconds=duration_sec,
            auto_export=True,
        )
        return (
            f"⚠️ Incident signalé pour '{target}' ({reason}).\n"
            f"Statut : {res.message}\n"
            f"La configuration OpenCode a été basculée sur le modèle de repli."
        )

    def _tool_list_models(self, args: Dict[str, Any]) -> str:
        query = (args.get("query") or "").lower().strip()
        only_free = bool(args.get("only_free", False))
        requires_tools = bool(args.get("requires_tools", False))
        limit = min(int(args.get("limit", 10)), 50)

        report = self.service.build_report(allow_fallback=True)
        models = report.models
        matches = []
        for m in models:
            if only_free and not m.is_free:
                continue
            if requires_tools and not m.supports_tools:
                continue
            if query and (query not in m.id.lower() and query not in m.provider.lower()):
                continue
            matches.append(m)

        if not matches:
            return "Aucun modèle trouvé correspondant aux critères spécifiés."

        lines = [f"Modèles trouvés ({len(matches)} au total, affichage des {min(len(matches), limit)} premiers) :"]
        for m in matches[:limit]:
            free_tag = "[GRATUIT]" if m.is_free else f"${m.cost_input_per_m:.2f}/M in, ${m.cost_output_per_m:.2f}/M out"
            tools_tag = "🛠️ Tools" if m.supports_tools else "No tools"
            lines.append(f"  • {m.id} (Score: {m.complexity_score}/5, Ctx: {m.context_window:,}, {tools_tag}) — {free_tag}")

        return "\n".join(lines)


def run_mcp_server(
    service: ApplicationService,
    in_stream: Optional[TextIO] = None,
    out_stream: Optional[TextIO] = None,
) -> None:
    """Boucle principale stdio du serveur MCP."""
    in_io = in_stream if in_stream is not None else sys.stdin
    out_io = out_stream if out_stream is not None else sys.stdout
    server = ModelPoolMCPServer(service)

    for line in in_io:
        clean = line.strip()
        if not clean:
            continue
        try:
            req = json.loads(clean)
        except json.JSONDecodeError as err:
            err_resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Erreur de syntaxe JSON : {err}"},
            }
            out_io.write(json.dumps(err_resp) + "\n")
            out_io.flush()
            continue

        resp = server.handle_request(req)
        if resp is not None:
            out_io.write(json.dumps(resp, ensure_ascii=False) + "\n")
            out_io.flush()
