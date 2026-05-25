# Remote-Pulse Windows installer (F1 STUB — completed in F7)
#
# Usage (future):
#   $env:RP_TOKEN = "eyJhbGc..."
#   iwr -useb https://rp.monxas.casa/install.ps1 | iex
#
# F1 does not ship a working Windows path. For now, use WSL2:
#   wsl -- sh -c "curl -fsSL http://<server>/install | sh -s -- --token=..."

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "Remote-Pulse — Windows installer (F1 stub)" -ForegroundColor Yellow
Write-Host "============================================" -ForegroundColor Yellow
Write-Host ""
Write-Host "Windows native install is scheduled for F7 (PyInstaller binary + winget)."
Write-Host ""
Write-Host "For now please use WSL2:"
Write-Host "  1. Install WSL2:  wsl --install -d Ubuntu"
Write-Host "  2. Inside WSL:    curl -fsSL http://<rp-server>/install | sh -s -- --token=<JWT>"
Write-Host ""
Write-Host "Tracking ticket: ADR-0008 phase F7." -ForegroundColor DarkGray
exit 1
