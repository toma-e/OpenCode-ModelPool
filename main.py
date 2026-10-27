"""Interface CLI de synchronisation, sélection, export et serveur web local."""

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
        description="OpenCode-ModelPool - Attribution automatique de modèles LLM pour agents OpenCode."
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Synchronise le catalogue OpenRouter (par défaut ; utilisez --sync-all pour tous les fournisseurs).",
    )
    parser.add_argument(
        "--sync-openrouter",
        action="store_true",
        help="Synchronise uniquement le catalogue public OpenRouter.",
    )
    parser.add_argument(
        "--sync-all",
        action="store_true",
        help="Synchronise l'ensemble des fournisseurs configurés (OpenRouter, Ollama local, APIs directes).",
    )
    parser.add_argument("--no-fallback", action="store_true", help="Désactive le surclassement automatique.")
    parser.add_argument(
        "--filter-keys",
        action="store_true",
        help="Ne retient dans le vivier d'attribution que les modèles rattachés à des clés API disponibles ou locaux/gratuits.",
    )
    parser.add_argument(
        "--no-ollama",
        action="store_true",
        help="Désactive l'interrogation d'Ollama local lors de la synchronisation.",
    )
    parser.add_argument(
        "--status-keys",
        action="store_true",
        help="Affiche l'état des clés API et des fournisseurs détectés dans l'environnement local.",
    )
    parser.add_argument(
        "--refresh-access",
        action="store_true",
        help="Interroge les APIs directes (Google, Mistral, Groq...) pour vérifier les modèles réellement accessibles avec vos clés.",
    )
    parser.add_argument(
        "--import-models",
        type=Path,
        metavar="JSON_FILE",
        help="Valide et intègre un fichier JSON de modèles (ex: résultat de Gemini Deep Research) dans le catalogue.",
    )
    parser.add_argument(
        "--provider-priority",
        type=str,
        default=None,
        metavar="LIST",
        help="Ordre de priorité des fournisseurs séparés par des virgules (ex: ollama,groq,mistralai,openrouter).",
    )
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
        "--check-ready",
        action="store_true",
        help="Contrôle strict d'exécutabilité : renvoie un code de sortie 1 si un agent n'a pas de cible prête (clé vérifiée ou service local actif).",
    )
    parser.add_argument(
        "--export",
        nargs="?",
        const="config/opencode.json",
        help="Exporte la configuration OpenCode (défaut : config/opencode.json, ex: ~/.config/opencode/opencode.json ou .opencode/opencode.json).",
    )
    parser.add_argument(
        "--diff",
        "--preview",
        nargs="?",
        const="config/opencode.json",
        metavar="PATH",
        dest="diff",
        help="Prévisualise le diff unifié de la configuration OpenCode sans écrire sur le disque (MP-206).",
    )
    parser.add_argument(
        "--rollback",
        nargs="?",
        const="config/opencode.json",
        metavar="PATH",
        help="Restaure la configuration OpenCode depuis la dernière sauvegarde horodatée ou .bak (MP-206).",
    )
    parser.add_argument(
        "--failover",
        "--report-error",
        type=str,
        default=None,
        metavar="AGENT_OR_MODEL",
        dest="failover",
        help="Signale une erreur (429, quota, 5xx) sur un agent ou un modèle, le met en quarantaine et bascule automatiquement sur le modèle de repli.",
    )
    parser.add_argument(
        "--error-reason",
        type=str,
        default="rate_limit",
        choices=["rate_limit", "quota_exceeded", "insufficient_credits", "service_unavailable", "auth_error", "other"],
        help="Nature de l'erreur motivant le repli (défaut : rate_limit).",
    )
    parser.add_argument(
        "--cooldown-minutes",
        type=int,
        default=None,
        metavar="MINUTES",
        help="Durée personnalisée de mise en quarantaine en minutes (défaut automatique selon --error-reason).",
    )
    parser.add_argument(
        "--list-cooldowns",
        action="store_true",
        help="Affiche les modèles et fournisseurs actuellement en quarantaine (cooldown actif).",
    )
    parser.add_argument(
        "--clear-cooldowns",
        nargs="?",
        const="all",
        default=None,
        metavar="TARGET_ID",
        help="Lève la quarantaine de tous les modèles (ou uniquement de TARGET_ID) et les réhabilite.",
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
    budget_by_agent = {r.agent_name: r for r in report.budget.agent_reports}
    for index, (agent, result) in enumerate(zip(report.agents, report.results)):
        print("-" * 75)
        print(f"Agent : {agent.name} — {agent.description}")
        target = report.execution_targets[index] if index < len(report.execution_targets) else None
        agent_budget = budget_by_agent.get(agent.name)
        if result.model:
            status = "FALLBACK / SURCLASSEMENT" if result.is_fallback else "EXACT"
            print(f"  Statut            : [{status}] {result.reason}")
            print(f"  Modèle retenu     : {result.model.id}")
            if target:
                print(f"  Canal d'exécution : {target.description_label} (ID OpenCode: {target.formatted_model_id})")
                if target.pricing_source:
                    print(f"  Source tarifaire  : {target.pricing_source}")
            if agent_budget:
                if not agent_budget.is_estimable:
                    print("  Coût estimé       : Non estimable (tarifs non répertoriés)")
                elif agent_budget.is_local:
                    print("  Coût estimé       : $0.0000 (0$ API, hors infrastructure)")
                else:
                    print(f"  Coût estimé       : ${agent_budget.monthly_total_cost:.4f}")
                if agent_budget.quota_warning:
                    print(f"  Alerte quota      : {agent_budget.quota_warning}")
            chain = report.fallback_chains.get(agent.name, [])
            if chain:
                print(f"  Chaîne de repli   : {' -> '.join(chain)}")
        else:
            print(f"  Aucun modèle compatible : {result.reason}")
    print("-" * 75)
    if report.budget.is_total_estimable:
        print(f"💰 Coût mensuel total estimé : ${report.budget.total_monthly_cost:.4f}")
    else:
        print("💰 Coût mensuel total estimé : Non estimable (au moins un modèle a des tarifs non répertoriés)")
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
    filter_by_keys = getattr(args, "filter_keys", False)
    include_ollama = not getattr(args, "no_ollama", False)

    custom_priority: list[str] | None = None
    if getattr(args, "provider_priority", None):
        custom_priority = [p.strip().lower() for p in args.provider_priority.split(",") if p.strip()]

    if getattr(args, "status_keys", False):
        creds = service.get_providers_status()
        from src.providers.access import read_provider_access
        cached = read_provider_access(service.access_path)
        print("\n🔑 État des fournisseurs et clés API détectés :\n")
        print(f"{'Fournisseur':<12} {'Disponible':<12} {'Source':<15} {'Modèles vérifiés':<18} {'Clé masquée'}")
        print("-" * 75)
        for prov, c in sorted(creds.items()):
            status_symbol = "✅ Oui" if c.is_available else "❌ Non"
            masked = c.masked_key if c.masked_key else ("(service local)" if prov == "ollama" else "(aucune)")
            entry = cached.get(prov)
            if prov == "ollama":
                verified_str = "(service local)"
            elif prov == "openrouter":
                verified_str = "(catalogue public)"
            elif entry and entry.masked_key == c.masked_key:
                if entry.status == "ok":
                    verified_str = f"✅ {len(entry.model_ids)} modèle(s)"
                elif entry.status == "empty":
                    verified_str = "⚠️  0 modèle"
                else:
                    verified_str = "❌ erreur"
            elif c.is_available:
                verified_str = "⚠️  non vérifié"
            else:
                verified_str = "-"
            print(f"{prov:<12} {status_symbol:<12} {c.source:<15} {verified_str:<18} {masked}")
        print("-" * 75)
        return 0

    if getattr(args, "refresh_access", False):
        print("🔍 Vérification des modèles réellement accessibles auprès des APIs directes...")
        refreshed = service.refresh_provider_access(allow_fallback=allow_fallback)
        if not refreshed.ok:
            LOGGER.error("Échec de la vérification des accès : %s", refreshed.message)
            print(f"❌ {refreshed.message}", file=sys.stderr)
            return 1
        print(f"✅ {refreshed.message}")
        if refreshed.report:
            render_results(refreshed.report)
        return 0

    if getattr(args, "import_models", None):
        import_path = Path(args.import_models).expanduser()
        print(f"📥 Intégration des modèles depuis {import_path}...")
        res = service.import_models_from_json(import_path, allow_fallback=allow_fallback, filter_by_keys=filter_by_keys)
        if not res.ok:
            LOGGER.error("Échec de l'intégration : %s", res.message)
            print(f"❌ {res.message}", file=sys.stderr)
            return 1
        print(f"✅ {res.message}")
        if res.report:
            render_results(res.report)
        return 0

    if getattr(args, "rollback", None):
        res = service.rollback_export(args.rollback)
        if not res.ok:
            LOGGER.error("Échec de la restauration : %s", res.message)
            print(f"❌ {res.message}", file=sys.stderr)
            return 1
        print(f"✅ {res.message}")
        return 0

    if getattr(args, "list_cooldowns", False):
        cooldowns = service.get_active_cooldowns()
        if not cooldowns:
            print("✅ Aucun modèle ni fournisseur n'est actuellement en quarantaine.")
            return 0
        print(f"\n⏳ Modèles / Fournisseurs en quarantaine active ({len(cooldowns)}) :\n")
        print(f"{'Cible':<48} {'Motif':<22} {'Temps restant'}")
        print("-" * 85)
        for entry in cooldowns:
            rem_min = max(1, (entry.remaining_seconds() + 59) // 60)
            print(f"{entry.target_id:<48} {entry.reason:<22} ~{rem_min} min (exp: {entry.expires_at[:19]}Z)")
        print("-" * 85)
        return 0

    if getattr(args, "clear_cooldowns", None) is not None:
        target = None if args.clear_cooldowns == "all" else args.clear_cooldowns
        res = service.clear_cooldowns(
            target_id=target,
            allow_fallback=allow_fallback,
            filter_by_keys=filter_by_keys,
            auto_export=bool(args.export),
            export_path=args.export,
        )
        if not res.ok:
            print(f"❌ {res.message}", file=sys.stderr)
            return 1
        print(f"✅ {res.message}")
        if res.report:
            render_results(res.report)
        return 0

    if getattr(args, "failover", None):
        duration_sec = args.cooldown_minutes * 60 if getattr(args, "cooldown_minutes", None) else None
        export_target = args.export if args.export else "config/opencode.json"
        res = service.report_model_error(
            target_or_agent=args.failover,
            reason=getattr(args, "error_reason", "rate_limit"),
            duration_seconds=duration_sec,
            allow_fallback=allow_fallback,
            filter_by_keys=filter_by_keys,
            auto_export=True,
            export_path=export_target,
        )
        if not res.ok:
            LOGGER.error("Échec de la bascule : %s", res.message)
            print(f"❌ {res.message}", file=sys.stderr)
            return 1
        print(f"⚡ {res.message}")
        if res.report:
            render_results(res.report)
        return 0

    if getattr(args, "diff", None):
        preview = service.preview_export(
            args.diff,
            allow_fallback=allow_fallback,
            filter_by_keys=filter_by_keys,
            custom_priority=custom_priority,
        )
        if not preview["is_valid"]:
            print("❌ Erreur de validation de la configuration :", file=sys.stderr)
            for err in preview["validation_errors"]:
                print(f"  • {err}", file=sys.stderr)
            return 1
        print(f"📄 Prévisualisation du diff pour {preview['target_path']} :\n")
        print(preview["diff"] if preview["diff"] else "(Aucune différence avec le fichier existant)")
        return 0

    if getattr(args, "sync_all", False):
        print("🔄 Synchronisation du catalogue multi-fournisseurs (OpenRouter, Ollama, APIs directes)...")
        synced = service.sync_catalogue(
            allow_fallback=allow_fallback,
            multi_provider=True,
            include_ollama=include_ollama,
            filter_by_keys=filter_by_keys,
        )
        if not synced.ok:
            LOGGER.error("Échec de synchronisation multi-fournisseurs : %s", synced.message)
            print(f"❌ {synced.message}", file=sys.stderr)
            return 1
        print(f"✅ {synced.message}")

    elif getattr(args, "sync_openrouter", False) or args.sync:
        print("🔄 Synchronisation du catalogue OpenRouter...")
        synced = service.sync_catalogue(
            allow_fallback=allow_fallback,
            multi_provider=False,
            include_ollama=False,
            filter_by_keys=filter_by_keys,
        )
        if not synced.ok:
            LOGGER.error("Échec de synchronisation OpenRouter : %s", synced.message)
            print(f"❌ {synced.message}", file=sys.stderr)
            return 1
        print(f"✅ {synced.message}")

    elif args.serve is None and not service.models_path.exists():
        print("🔄 Catalogue de modèles absent : initialisation via OpenRouter...")
        synced = service.sync_catalogue(
            allow_fallback=allow_fallback,
            multi_provider=False,
            include_ollama=False,
            filter_by_keys=filter_by_keys,
        )
        if not synced.ok:
            LOGGER.error("Échec d'initialisation du catalogue : %s", synced.message)
            print(f"❌ {synced.message}", file=sys.stderr)
            return 1
        print(f"✅ {synced.message}")

    if args.serve is not None:
        from src.web import serve_local_interface

        print(f"🌐 Interface locale : http://127.0.0.1:{args.serve}/")
        serve_local_interface(service, port=args.serve, allow_fallback=allow_fallback)
        return 0

    built = service.build_report_result(
        allow_fallback=allow_fallback,
        filter_by_keys=filter_by_keys,
        custom_priority=custom_priority,
    )
    if not built.ok or built.report is None:
        LOGGER.error("Erreur de chargement : %s", built.message)
        print(f"❌ {built.message}", file=sys.stderr)
        return 2

    render_results(built.report)

    if getattr(args, "check_ready", False):
        is_ready, reasons = service.check_fleet_readiness(built.report)
        if not is_ready:
            print("\n❌ Contrôle strict d'exécutabilité échoué :", file=sys.stderr)
            for reason in reasons:
                print(f"  • {reason}", file=sys.stderr)
            return 1
        print("\n✅ Contrôle strict d'exécutabilité réussi : tous les agents disposent d'un canal d'exécution prêt.")
        if not args.validate and not args.export:
            return 0

    if getattr(args, "validate", False):
        unassigned = [r.agent_name for r in built.report.results if r.model is None]
        if unassigned:
            print(f"❌ Validation échouée : {len(unassigned)} agent(s) sans modèle ({', '.join(unassigned)}).", file=sys.stderr)
            return 1
        print("✅ Validation réussie : tous les agents disposent d'un modèle compatible.")
        if not args.export:
            return 0

    if args.export:
        exported = service.export_config(
            args.export,
            allow_fallback=allow_fallback,
            filter_by_keys=filter_by_keys,
            custom_priority=custom_priority,
        )
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
