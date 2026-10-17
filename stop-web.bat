@echo off
setlocal
chcp 65001 >nul

REM Arrete le serveur OpenCode-ModelPool en cours d'execution dans WSL

echo ========================================
echo Arret du serveur OpenCode-ModelPool
echo ========================================
echo.

echo Recherche des processus Python en cours...
wsl bash -c "pkill -f 'python3 main.py --serve'"

if errorlevel 1 (
    echo [INFO] Aucun processus serveur trouve ou deja arrete.
) else (
    echo [OK] Signal d'arret envoye avec succes.
)

echo.
echo Verification...
wsl bash -c "ps aux | grep 'python3 main.py --serve' | grep -v grep" >nul 2>&1
if errorlevel 1 (
    echo [OK] Aucun processus serveur en cours d'execution.
) else (
    echo [AVERTISSEMENT] Des processus sont encore actifs.
)

echo.
pause
