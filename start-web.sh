#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================"
echo "OpenCode-ModelPool - Interface Web Locale"
echo "========================================"
echo ""

# Verifier si le serveur tourne deja
if curl -s -f http://127.0.0.1:8765/ > /dev/null 2>&1; then
    echo "[INFO] Le serveur est deja actif sur http://127.0.0.1:8765/"
    exit 0
fi

echo "[1/2] Demarrage du serveur..."
python3 main.py --serve 8765 &
SERVER_PID=$!

cleanup() {
    echo ""
    echo "Arret du serveur (PID $SERVER_PID)..."
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

echo "[2/2] Attente du demarrage du serveur..."
for i in {1..10}; do
    if curl -s -f http://127.0.0.1:8765/ > /dev/null 2>&1; then
        echo "OK Serveur demarre avec succes."
        break
    fi
    sleep 1
done

echo ""
echo "========================================"
echo "Serveur lance sur http://127.0.0.1:8765/"
echo "PID du serveur: $SERVER_PID"
echo "Pour arreter le serveur, appuyez sur Ctrl+C ou executez ./stop-web.sh"
echo "========================================"
echo ""

wait "$SERVER_PID"
