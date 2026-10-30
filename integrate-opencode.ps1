# OpenCode-ModelPool - Script d'intégration clé en main dans OpenCode (Windows PowerShell)
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "OpenCode-ModelPool - Integration Automatique dans OpenCode" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host ""

if (Get-Command wsl.exe -ErrorAction SilentlyContinue) {
    Write-Host "[WSL] Configuration de l'integration dans l'environnement WSL et Windows..." -ForegroundColor Yellow
    # Conversion du chemin Windows en chemin WSL
    $wslPath = $scriptDir -replace '\\', '/' -replace 'C:', '/mnt/c'
    wsl.exe -e bash -c "cd '$wslPath' && python3 main.py --integrate"
} elseif (Get-Command python.exe -ErrorAction SilentlyContinue) {
    Write-Host "[Windows] Configuration de l'integration via Python local..." -ForegroundColor Yellow
    python.exe "$scriptDir\main.py" --integrate
} else {
    Write-Host "Erreur : Ni WSL ni Python ne sont detectes dans votre PATH." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Integration terminee avec succes ! Redemarrez OpenCode pour utiliser les commandes /modelpool." -ForegroundColor Green
