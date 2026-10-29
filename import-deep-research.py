#!/usr/bin/env python3
"""Script interactif et automatisé d'importation de résultats Gemini Deep Research dans OpenCode-ModelPool.

Permet :
1. De sélectionner interactivement ou de passer en argument un fichier JSON issu de Deep Research.
2. De valider automatiquement chaque modèle (types, contraintes, prix finis, tokens, complexité).
3. D'exclure les modèles non-LLM (audio, musique, embeddings purs, tts, robotique).
4. De créer une sauvegarde horodatée dans data/backups/ et de fusionner atomiquement dans data/models.json.
5. De recalculer et d'afficher les attributions des agents et la simulation budgétaire mise à jour.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Résolution de la racine du projet
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.service import ApplicationService  # noqa: E402


def normalize_user_path(raw_input_str: str) -> Path:
    """Normalise un chemin utilisateur (supporte chemins POSIX, Windows C:\\... et UNC \\\\wsl.localhost\\...)."""
    import re
    cleaned = raw_input_str.strip('\"\' \t\r\n')
    # Normalisation des antislashs
    unix_style = cleaned.replace("\\", "/")

    # Cas 1 : Chemin Windows classique C:/Users/... -> /mnt/c/Users/...
    if re.match(r"^[a-zA-Z]:/", unix_style):
        drive = unix_style[0].lower()
        return Path(f"/mnt/{drive}{unix_style[2:]}")

    # Cas 2 : Chemin UNC Windows vers WSL //wsl.localhost/Ubuntu/home/... -> /home/...
    m = re.match(r"^//wsl(\.localhost)?/[^/]+(/.*)$", unix_style, re.IGNORECASE)
    if m:
        return Path(m.group(2))

    return Path(cleaned).expanduser()


def prompt_select_file(search_dir: Path) -> Path:
    """Propose interactivement à l'utilisateur de choisir un fichier JSON ou de saisir son chemin."""
    print("=" * 75)
    print("🤖 Assistant d'intégration Gemini Deep Research -> OpenCode-ModelPool")
    print("=" * 75)

    # Recherche des fichiers JSON candidats récents dans le dossier ou sous-dossiers courants
    candidate_files: list[Path] = []
    scan_dirs = [
        search_dir,
        search_dir / "Ressources",
        search_dir / "ressources",
        search_dir / "docs" / "google_ai_pro" / "deep_research",
        Path.home() / "Downloads",
        Path("/tmp"),
        # Dossier Téléchargements Windows sous WSL (/mnt/c/Users/*/Downloads)
        *list(Path("/mnt/c/Users").glob("*/Downloads")),
    ]

    for d in scan_dirs:
        if d.is_dir():
            try:
                for p in d.glob("*.json"):
                    # Ignorer les flux ADS Windows (:Zone.Identifier), les fichiers de config ou package
                    if ":" in p.name or "models.json" in p.name or "auth.json" in p.name or "package" in p.name:
                        continue
                    if p not in candidate_files and p.is_file():
                        candidate_files.append(p)
            except OSError:
                pass

    # Tri par date de modification décroissante
    candidate_files.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    recent_candidates = candidate_files[:8]

    if recent_candidates:
        print("\nFichiers JSON candidats détectés récemment :")
        for idx, candidate in enumerate(recent_candidates, start=1):
            try:
                rel = candidate.relative_to(search_dir)
                display_path = f"./{rel}"
            except ValueError:
                display_path = str(candidate)
            print(f"  [{idx}] {display_path}")
        print("  [0] Saisir manuellement un autre chemin de fichier")

        while True:
            choice = input("\nChoisissez un numéro (ou appuyez sur Entrée pour le [1]) : ").strip()
            if not choice:
                return recent_candidates[0]
            if choice == "0":
                break
            try:
                val = int(choice)
                if 1 <= val <= len(recent_candidates):
                    return recent_candidates[val - 1]
            except ValueError:
                pass
            print(f"Option invalide. Choisissez entre 0 et {len(recent_candidates)}.")

    while True:
        manual_path_str = input("\nEntrez le chemin vers votre fichier JSON de Deep Research (ou 'q' pour quitter) : ").strip()
        if not manual_path_str or manual_path_str.lower() in {"q", "quit", "exit"}:
            print("Annulé.")
            sys.exit(0)
        p = normalize_user_path(manual_path_str)
        if p.is_file():
            return p
        print(f"❌ Le fichier '{p}' n'existe pas ou n'est pas accessible. Réessayez.")



def main() -> int:
    parser = argparse.ArgumentParser(
        description="Assistant d'intégration sécurisée de résultats Gemini Deep Research dans OpenCode-ModelPool."
    )
    parser.add_argument(
        "file",
        nargs="?",
        type=Path,
        help="Chemin vers le fichier JSON contenant les modèles (optionnel, mode interactif par défaut).",
    )
    parser.add_argument(
        "--no-fallback",
        action="store_true",
        help="Désactive le surclassement économique lors du recalcul.",
    )
    parser.add_argument(
        "--filter-keys",
        action="store_true",
        help="Filtre l'attribution en fonction des clés d'API disponibles.",
    )

    args = parser.parse_args()
    service = ApplicationService(BASE_DIR)

    if args.file:
        target_path = normalize_user_path(str(args.file))
        if not target_path.is_file():
            print(f"❌ Erreur : Le fichier spécifié est introuvable : {target_path}", file=sys.stderr)
            return 1
    else:
        target_path = prompt_select_file(BASE_DIR)

    print(f"\n🚀 Traitement du fichier : {target_path}")
    print("⏳ Validation des schémas, exclusion des non-LLM et fusion atomique en cours...")

    result = service.import_models_from_json(
        target_path,
        allow_fallback=not args.no_fallback,
        filter_by_keys=args.filter_keys,
    )

    if not result.ok:
        print(f"\n❌ Échec de l'intégration : {result.message}", file=sys.stderr)
        return 1

    print(f"\n✅ {result.message}")

    if result.report:
        from main import render_results
        render_results(result.report)

    print("\n💡 Vous pouvez maintenant exporter la configuration OpenCode mise à jour avec :")
    print("   python3 main.py --export\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
