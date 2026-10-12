"""Interface CLI de synchronisation, sélection, export et serveur web local."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Sequence

from src.service import ApplicationService, FleetReport, load_data

LOGGER = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_SERVE_PORT = 8765
__all__ = ["BASE_DIR", "build_parser", "load_data", "main", "render_results", "run"]


def _valid_port(value: str) -> int:
    try:
        port = int(value)
        if not (1 <= port <= 65535):
            raise ValueError
        return port
    except ValueError:
        raise argparse.ArgumentTypeError(f"Port invalide '{value}'. Un entier compris entre 1 et 65535 est attendu.")


def build_parser() -> argparse.ArgumentParser:
    """Construit le parseur d'arguments de la ligne de commande."""
    parser = argparse.ArgumentParser(
        description="ModelScope - Attribution automatique de modèles LLM pour agents OpenCode."
    )
    parser.add_argument("--sync", action="store_true", help="Synchronise le catalogue OpenRouter avec backup.")
    parser.add_argument("--no-fallback", action="store_true", help="Désactive le surclassement automatique.")
    parser.add_argument(
        "--models",
        type=Path,
        metavar="PATH",
        help="Chemin personnalisé vers models.json (défaut : data/models.json).",
    )
    parser.add_argument(
        "--agents",
        type=Path,
        metavar="PATH",
        help="Chemin personnalisé vers agents_requirements.json (défaut : config/agents_requirements.json).",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validation sans export : renvoie un code de sortie 1 si au moins un agent reste non attribué.",
    )
    parser.add_argument(
        "--export",
        nargs="?",
        const="config/opencode.json",
        help="Exporte la configuration OpenCode (chemin facultatif).",
    )
    parser.add_argument(
        "--serve",
        nargs="?",
        const=DEFAULT_SERVE_PORT,
        type=_valid_port,
        metavar="PORT",
        help=f"Démarre l'interface web locale sur 127.0.0.1 (défaut : {DEFAULT_SERVE_PORT}, plage : 1-65535).",
    )
    return parser


def render_results(report: FleetReport) -> None:
    """Affiche les attributions et la simulation budgétaire d'un rapport."""
    print(f"\n🤖 Configuration des agents ({len(report.agents)}) :\n")
    for agent, result in zip(report.agents, report.results):
        print("-" * 75)
        print(f"Agent : {agent.name} — {agent.description}")
        if result.model:
            status = "FALLBACK / SURCLASSEMENT" if result.is_fallback else "EXACT"
            print(f"  Statut      : [{status}] {result.reason}")
            print(f"  Modèle retenu : {result.model.id}")
        else:
            print(f"  Aucun modèle compatible : {result.reason}")
    print("-" * 75)
    print(f"💰 Coût mensuel total estimé : ${report.budget.total_monthly_cost:.4f}")
    print(f"📊 Volume total estimé : {report.budget.total_tokens:,} tokens/mois")
    if report.diagnostics:
        print("\n⚠️  Diagnostics :")
        for diag in report.diagnostics:
            print(f"  • {diag}")


def run(args: argparse.Namespace, base_dir: Path = BASE_DIR) -> int:
    """Exécute le flux CLI et renvoie un code de sortie POSIX."""
    models_path = args.models.resolve() if getattr(args, "models", None) else None
    agents_path = args.agents.resolve() if getattr(args, "agents", None) else None
    service = ApplicationService(base_dir, models_path=models_path, agents_path=agents_path)
    allow_fallback = not args.no_fallback
    if args.sync or (args.serve is None and not service.models_path.exists()):
        print("🔄 Synchronisation du catalogue depuis OpenRouter...")
        synced = service.sync_catalogue(allow_fallback=allow_fallback)
        if not synced.ok:
            LOGGER.error("Échec de synchronisation : %s", synced.message)
            print(f"❌ {synced.message}", file=sys.stderr)
            return 1
        print(f"✅ {synced.message}")
    if args.serve is not None:
        from src.web import serve_local_interface

        print(f"🌐 Interface locale : http://127.0.0.1:{args.serve}/")
        serve_local_interface(service, port=args.serve, allow_fallback=allow_fallback)
        return 0
    built = service.build_report_result(allow_fallback=allow_fallback)
    if not built.ok or built.report is None:
        LOGGER.error("Erreur de chargement : %s", built.message)
        print(f"❌ {built.message}", file=sys.stderr)
        return 2
    render_results(built.report)
    if getattr(args, "validate", False):
        unassigned = [r.agent_name for r in built.report.results if r.model is None]
        if unassigned:
            print(f"❌ Validation échouée : {len(unassigned)} agent(s) sans modèle ({', '.join(unassigned)}).", file=sys.stderr)
            return 1
        print("✅ Validation réussie : tous les agents disposent d'un modèle compatible.")
        if not args.export:
            return 0
    if args.export:
        exported = service.export_config(args.export, allow_fallback=allow_fallback)
        if not exported.ok:
            LOGGER.error("Échec d'export : %s", exported.message)
            print(f"❌ {exported.message}", file=sys.stderr)
            return 1
        print(f"🚀 {exported.message}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Point d'entrée CLI testable ; renvoie 0 en cas de succès."""
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
