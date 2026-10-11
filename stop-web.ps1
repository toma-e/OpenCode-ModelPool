# Arret du serveur ModelScope en cours d'execution dans WSL
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Arret du serveur ModelScope" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "Recherche des processus Python en cours..." -ForegroundColor Yellow
wsl.exe bash -c "pkill -f 'python3 main.py --serve'"
if ($LASTEXITCODE -ne 0) {
    Write-Host "[INFO] Aucun processus serveur trouve ou deja arrete." -ForegroundColor Gray
} else {
    Write-Host "[OK] Serveur arrete avec succes." -ForegroundColor Green
}

Write-Host ""
Write-Host "Verification..." -ForegroundColor Yellow
wsl.exe bash -c "ps aux | grep 'python3 main.py --serve' | grep -v grep" > $null 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "[OK] Aucun processus serveur en cours d'execution." -ForegroundColor Green
} else {
    Write-Host "[AVERTISSEMENT] Des processus sont encore actifs." -ForegroundColor Red
}
Write-Host ""
