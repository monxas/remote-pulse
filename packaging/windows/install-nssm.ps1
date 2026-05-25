# install-nssm.ps1 — Remote-Pulse Windows service installer (F7 / ADR-0008)
#
# Provides function Install-RemotePulseService:
#   - Downloads + caches NSSM (https://nssm.cc/release/nssm-2.24.zip)
#   - Creates Windows service 'RemotePulseAgent'
#   - Configures AppDirectory, AppParameters, AppEnvironment
#   - Sets stdout/stderr file rotation (10MB online rotate)
#   - Sets recovery: Restart on failure, 5s delay
#   - Idempotent: if service exists, updates config and restarts
#
# Source via dot-sourcing from scripts/install.ps1, or call standalone:
#   . .\install-nssm.ps1
#   Install-RemotePulseService -InstallDir 'C:\Program Files\RemotePulse' `
#                              -DataDir    'C:\ProgramData\RemotePulse' `
#                              -ServiceName 'RemotePulseAgent'

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Script:NssmZipUrl    = 'https://nssm.cc/release/nssm-2.24.zip'
$Script:NssmZipSha256 = '52897F289CD4523A89AFD2A2092518EC1F0BB28A38C72BF45EBD60E1FAE36287'  # nssm 2.24 zip
$Script:NssmVersion   = '2.24'

function Get-Nssm {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string]$InstallDir,
        [switch]$Offline
    )
    $nssm = Join-Path $InstallDir 'nssm.exe'
    if (Test-Path $nssm) { return $nssm }

    if ($Offline) {
        throw "nssm.exe missing at $nssm and -Offline set. Pre-stage nssm.exe before retry."
    }

    Write-Host "==> Downloading NSSM $Script:NssmVersion" -ForegroundColor Cyan
    $zipPath = Join-Path $env:TEMP 'nssm.zip'
    $oldPP = $ProgressPreference
    try {
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest -Uri $Script:NssmZipUrl -OutFile $zipPath -UseBasicParsing
    } finally { $ProgressPreference = $oldPP }

    $actual = (Get-FileHash $zipPath -Algorithm SHA256).Hash.ToUpper()
    if ($actual -ne $Script:NssmZipSha256.ToUpper()) {
        throw "NSSM zip SHA256 mismatch (expected $Script:NssmZipSha256, got $actual). Aborting."
    }

    $tmpDir = Join-Path $env:TEMP "nssm-extract-$(Get-Random)"
    Expand-Archive -Path $zipPath -DestinationPath $tmpDir -Force
    $arch = if ([Environment]::Is64BitOperatingSystem) { 'win64' } else { 'win32' }
    $src = Get-ChildItem -Path $tmpDir -Recurse -Filter nssm.exe | Where-Object { $_.FullName -match "\\$arch\\" } | Select-Object -First 1
    if (-not $src) { throw "Could not find nssm.exe in extracted archive" }
    Copy-Item -Force $src.FullName $nssm
    Remove-Item -Recurse -Force $tmpDir, $zipPath -ErrorAction SilentlyContinue

    Write-Host "OK  NSSM installed at $nssm" -ForegroundColor Green
    return $nssm
}

function Invoke-Nssm {
    param(
        [Parameter(Mandatory)] [string]$NssmPath,
        [Parameter(Mandatory)] [string[]]$Arguments
    )
    Write-Verbose "nssm.exe $($Arguments -join ' ')"
    & $NssmPath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "nssm $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

function Install-RemotePulseService {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory)] [string]$InstallDir,
        [Parameter(Mandatory)] [string]$DataDir,
        [string]$ServiceName = 'RemotePulseAgent',
        [string]$DisplayName = 'Remote-Pulse Agent',
        [string]$Description = 'Remote-Pulse fleet monitoring agent. https://github.com/monxas/remote-pulse',
        [switch]$Offline
    )

    $rpExe   = Join-Path $InstallDir 'rp.exe'
    $logDir  = Join-Path $DataDir 'logs'
    $stdout  = Join-Path $logDir 'stdout.log'
    $stderr  = Join-Path $logDir 'stderr.log'

    if (-not (Test-Path $rpExe))     { throw "rp.exe not found at $rpExe — install agent first" }
    if (-not (Test-Path $logDir))    { New-Item -ItemType Directory -Force -Path $logDir | Out-Null }

    $nssm = Get-Nssm -InstallDir $InstallDir -Offline:$Offline

    $existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "==> Service $ServiceName exists — updating config" -ForegroundColor Cyan
        if ($existing.Status -eq 'Running') {
            if ($PSCmdlet.ShouldProcess($ServiceName, 'stop service')) {
                Invoke-Nssm -NssmPath $nssm -Arguments @('stop', $ServiceName)
            }
        }
    } else {
        Write-Host "==> Installing service $ServiceName" -ForegroundColor Cyan
        if ($PSCmdlet.ShouldProcess($ServiceName, 'nssm install')) {
            Invoke-Nssm -NssmPath $nssm -Arguments @('install', $ServiceName, $rpExe, 'heartbeat', '--daemon')
        }
    }

    # Core service config
    $set = @(
        @('set', $ServiceName, 'Application',     $rpExe),
        @('set', $ServiceName, 'AppParameters',   'heartbeat --daemon'),
        @('set', $ServiceName, 'AppDirectory',    $InstallDir),
        @('set', $ServiceName, 'DisplayName',     $DisplayName),
        @('set', $ServiceName, 'Description',     $Description),
        @('set', $ServiceName, 'Start',           'SERVICE_AUTO_START'),
        @('set', $ServiceName, 'ObjectName',      'LocalSystem'),
        @('set', $ServiceName, 'AppEnvironmentExtra', "RP_CONFIG=$(Join-Path $DataDir 'config.toml')",
                                                     "RP_DATA_DIR=$DataDir"),
        # Recovery: always restart with 5s delay
        @('set', $ServiceName, 'AppExit',          'Default', 'Restart'),
        @('set', $ServiceName, 'AppRestartDelay',  '5000'),
        @('set', $ServiceName, 'AppThrottle',      '10000'),
        # Logging — rotate online at 10MB, keep both stdout+stderr
        @('set', $ServiceName, 'AppStdout',        $stdout),
        @('set', $ServiceName, 'AppStderr',        $stderr),
        @('set', $ServiceName, 'AppRotateFiles',   '1'),
        @('set', $ServiceName, 'AppRotateOnline',  '1'),
        @('set', $ServiceName, 'AppRotateSeconds', '86400'),
        @('set', $ServiceName, 'AppRotateBytes',   '10485760'),
        @('set', $ServiceName, 'AppStdoutCreationDisposition', '4'),
        @('set', $ServiceName, 'AppStderrCreationDisposition', '4')
    )
    foreach ($cmd in $set) {
        if ($PSCmdlet.ShouldProcess($ServiceName, "nssm $($cmd -join ' ')")) {
            Invoke-Nssm -NssmPath $nssm -Arguments $cmd
        }
    }

    if ($PSCmdlet.ShouldProcess($ServiceName, 'start service')) {
        Invoke-Nssm -NssmPath $nssm -Arguments @('start', $ServiceName)
    }

    # Verify
    Start-Sleep -Seconds 2
    $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($svc -and $svc.Status -eq 'Running') {
        Write-Host "OK  Service $ServiceName running" -ForegroundColor Green
    } else {
        Write-Warning "Service $ServiceName state=$($svc.Status). Check $stderr for details."
    }
}

# When dot-sourced by install.ps1, this file just defines Install-RemotePulseService.
# To run standalone:
#   powershell -File install-nssm.ps1.runner.ps1
# We intentionally do NOT define a top-level param() block here to keep this
# file dot-source-friendly. Callers pass parameters when invoking the function.
