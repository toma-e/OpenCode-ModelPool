# Lanceur PowerShell pour l'interface web ModelScope
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "ModelScope - Interface Web Locale" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Verifier si le serveur tourne deja
try {
    $existing = (Invoke-WebRequest -Uri "http://127.0.0.1:8765/" -UseBasicParsing -TimeoutSec 1 -ErrorAction SilentlyContinue).StatusCode
    if ($existing -eq 200) {
        Write-Host "[INFO] Le serveur est deja actif sur http://127.0.0.1:8765/" -ForegroundColor Green
        Write-Host "Ouverture du navigateur..." -ForegroundColor Yellow
        Start-Process "http://127.0.0.1:8765/"
        exit 0
    }
} catch {}

# Resoudre le chemin WSL du projet
$wslProjectDir = ""
try {
    $wslProjectDir = (wsl wslpath "$PSScriptRoot" 2>$null).Trim()
} catch {}
if (-not $wslProjectDir) {
    $wslProjectDir = "/home/thomas/code/projets/ModelScope-Anti/modelscope-Anti"
}

# Lancer la surveillance pour ouvrir le navigateur des que pret
Start-Job -ScriptBlock {
    for ($i = 0; $i -lt 15; $i++) {
        try {
            $r = (Invoke-WebRequest -Uri "http://127.0.0.1:8765/" -UseBasicParsing -TimeoutSec 1).StatusCode
            if ($r -eq 200) {
                Start-Process "http://127.0.0.1:8765/"
                break
            }
        } catch {
            Start-Sleep -Seconds 1
        }
    }
} | Out-Null

Write-Host "Demarrage du serveur dans WSL..." -ForegroundColor Yellow
Write-Host "Serveur accessible sur : http://127.0.0.1:8765/" -ForegroundColor Green
Write-Host "Le navigateur va s'ouvrir automatiquement." -ForegroundColor Gray
Write-Host "Pour arreter le serveur : faites Ctrl+C ou fermez cette fenetre." -ForegroundColor Gray
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

wsl bash -c "cd `"$wslProjectDir`" && python3 main.py --serve 8765"
