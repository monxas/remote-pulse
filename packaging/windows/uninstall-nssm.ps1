# uninstall-nssm.ps1 — Remote-Pulse Windows uninstaller (F7 / ADR-0008)
#
# Stops and removes the NSSM service, optionally preserves data dirs.
#
# Usage (admin shell):
#   .\uninstall-nssm.ps1               # remove service + binaries, preserve data
#   .\uninstall-nssm.ps1 -PurgeData    # also delete C:\ProgramData\RemotePulse
#   .\uninstall-nssm.ps1 -WhatIf       # dry-run

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$InstallDir  = 'C:\Program Files\RemotePulse',
    [string]$DataDir     = 'C:\ProgramData\RemotePulse',
    [string]$ServiceName = 'RemotePulseAgent',
    [switch]$PurgeData,
    [switch]$KeepBinary
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-IsAdmin)) {
    Write-Error "This uninstaller requires Administrator. Re-run from elevated PowerShell."
    exit 1
}

$nssm = Join-Path $InstallDir 'nssm.exe'

# Stop + remove service
$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($svc) {
    if ($svc.Status -ne 'Stopped') {
        if ($PSCmdlet.ShouldProcess($ServiceName, 'stop service')) {
            try {
                if (Test-Path $nssm) { & $nssm stop $ServiceName | Out-Null }
                else { Stop-Service -Name $ServiceName -Force -ErrorAction Stop }
            } catch { Write-Warning "Stop failed: $($_.Exception.Message)" }
        }
    }
    if ($PSCmdlet.ShouldProcess($ServiceName, 'remove service')) {
        if (Test-Path $nssm) {
            & $nssm remove $ServiceName confirm | Out-Null
        } else {
            # Fallback to sc.exe
            & sc.exe delete $ServiceName | Out-Null
        }
        Write-Host "Service $ServiceName removed." -ForegroundColor Green
    }
} else {
    Write-Host "Service $ServiceName not present — skipping." -ForegroundColor DarkGray
}

# Optional: try winget uninstall (silent, ignore failure)
if (-not $KeepBinary -and (Get-Command winget -ErrorAction SilentlyContinue)) {
    if ($PSCmdlet.ShouldProcess('winget', 'uninstall Monxas.RemotePulse')) {
        & winget uninstall --id Monxas.RemotePulse --silent 2>$null | Out-Null
    }
}

# Remove binaries
if (-not $KeepBinary -and (Test-Path $InstallDir)) {
    if ($PSCmdlet.ShouldProcess($InstallDir, 'remove install dir')) {
        Remove-Item -Recurse -Force $InstallDir -ErrorAction SilentlyContinue
        Write-Host "Install dir removed: $InstallDir" -ForegroundColor Green
    }
}

# Data
if ($PurgeData) {
    if (Test-Path $DataDir) {
        if ($PSCmdlet.ShouldProcess($DataDir, 'purge data dir')) {
            Remove-Item -Recurse -Force $DataDir -ErrorAction SilentlyContinue
            Write-Host "Data dir purged: $DataDir" -ForegroundColor Yellow
        }
    }
} else {
    Write-Host "Data preserved at $DataDir (use -PurgeData to remove)." -ForegroundColor DarkGray
}

# Reminder: Tailscale not touched
Write-Host ""
Write-Host "Note: Tailscale was NOT uninstalled (may be used by other tools)." -ForegroundColor Cyan
Write-Host "      To remove: 'winget uninstall tailscale.tailscale' or via Settings > Apps."
