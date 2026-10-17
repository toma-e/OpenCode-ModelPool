#!/usr/bin/env bash
echo "========================================"
echo "Arret du serveur OpenCode-ModelPool"
echo "========================================"
echo ""
echo "Recherche des processus Python en cours..."
if pkill -f "python3 main.py --serve"; then
    echo "OK Serveur arrete avec succes"
else
    echo "INFO Aucun processus serveur trouve ou deja arrete"
fi

echo ""
echo "Verification..."
if ps aux | grep "python3 main.py --serve" | grep -v grep > /dev/null 2>&1; then
    echo "AVERTISSEMENT Des processus sont encore actifs:"
    ps aux | grep "python3 main.py --serve" | grep -v grep
else
    echo "OK Aucun processus serveur en cours d'execution"
fi
echo ""
