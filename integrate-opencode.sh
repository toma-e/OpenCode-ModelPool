#!/usr/bin/env bash
# OpenCode-ModelPool - Script d'intégration clé en main dans OpenCode (Linux / macOS / WSL)
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=========================================================="
echo "OpenCode-ModelPool - Intégration Automatique dans OpenCode"
echo "=========================================================="
echo ""

python3 main.py --integrate "$@"

echo ""
echo "✅ Intégration réussie ! Redémarrez OpenCode pour utiliser les commandes /modelpool."
