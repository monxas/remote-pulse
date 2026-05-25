# install-nssm.ps1 — STUB (F1-5 placeholder).
# Real Windows packaging lands in F7 (ADR-0008): winget package + PyInstaller
# single-file exe + NSSM service wrapper. See ../README.md.

Write-Host "F7 TODO: install via winget package + NSSM service" -ForegroundColor Yellow
Write-Host ""
Write-Host "Planned flow (F7):"
Write-Host "  1. winget install monxas.remote-pulse  (or download .exe from releases)"
Write-Host "  2. nssm install RemotePulse 'C:\Program Files\RemotePulse\rp.exe' heartbeat --daemon"
Write-Host "  3. nssm set RemotePulse AppStdout C:\ProgramData\RemotePulse\logs\stdout.log"
Write-Host "  4. nssm set RemotePulse AppStderr C:\ProgramData\RemotePulse\logs\stderr.log"
Write-Host "  5. nssm set RemotePulse Start SERVICE_AUTO_START"
Write-Host "  6. nssm start RemotePulse"
Write-Host ""
Write-Host "Tracking: ADR-0008 F7 (Windows installer honesto)." -ForegroundColor Cyan
exit 0
