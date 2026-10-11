@echo off
setlocal
chcp 65001 >nul

echo ========================================
echo ModelScope - Interface Web Locale
echo ========================================
echo.

REM Verifier si le serveur tourne deja
powershell -NoProfile -Command "try { $r = (Invoke-WebRequest -Uri 'http://127.0.0.1:8765/' -UseBasicParsing -TimeoutSec 1).StatusCode; if ($r -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
if not errorlevel 1 (
    echo [INFO] Le serveur est deja actif sur http://127.0.0.1:8765/
    echo Ouverture du navigateur...
    start "" http://127.0.0.1:8765/
    echo.
    echo Appuyez sur une touche pour quitter ce lanceur...
    pause >nul
    exit /b 0
)

REM Resoudre le chemin WSL du projet
set "SCRIPT_DIR=%~dp0"
REM Retirer l'antislash final si present
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

set "WSL_PROJECT_DIR="
REM 1. Tenter la conversion via wsl wslpath
for /f "usebackq delims=" %%i in (`wsl wslpath "%SCRIPT_DIR%" 2^>nul`) do set "WSL_PROJECT_DIR=%%i"

REM 2. Si echec ou UNC (\\wsl.localhost\... ou \\wsl$\...), extraire via PowerShell
if "%WSL_PROJECT_DIR%"=="" (
    for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "$p = '%SCRIPT_DIR%'; if ($p -match '^\\\\(?:wsl\.localhost|wsl\$)\\[^\\]+(?<wslpath>\\.*)$') { $matches['wslpath'] -replace '\\', '/' } else { (wsl wslpath -a $p 2>$null) }" 2^>nul`) do set "WSL_PROJECT_DIR=%%i"
)

if "%WSL_PROJECT_DIR%"=="" (
    echo [ERREUR] Impossible de determiner le chemin WSL du projet.
    echo Chemin Windows detecte : %SCRIPT_DIR%
    echo Vous pouvez lancer directement dans WSL avec : python3 main.py --serve 8765
    pause
    exit /b 1
)

echo [INFO] Repertoire WSL resolu : %WSL_PROJECT_DIR%
echo.

echo [1/2] Preparation de l'ouverture du navigateur...
start "" powershell -WindowStyle Hidden -NoProfile -Command "for ($i=0; $i -lt 15; $i++) { try { $r = (Invoke-WebRequest -Uri 'http://127.0.0.1:8765/' -UseBasicParsing -TimeoutSec 1).StatusCode; if ($r -eq 200) { Start-Process 'http://127.0.0.1:8765/'; break } } catch { Start-Sleep -Seconds 1 } }"

echo [2/2] Demarrage du serveur ModelScope dans WSL...
echo.
echo ========================================
echo Serveur actif sur http://127.0.0.1:8765/
echo Le navigateur va s'ouvrir automatiquement.
echo Pour arreter le serveur : fermez cette fenetre ou faites Ctrl+C.
echo ========================================
echo.

wsl -e bash -c "cd \"%WSL_PROJECT_DIR%\" && python3 main.py --serve 8765"
echo.
echo Le processus s'est termine avec le code de sortie %ERRORLEVEL%.
pause