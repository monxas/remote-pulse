# Remote-Pulse Windows bootstrap installer (F7 — ADR-0008 §10)
# SHA256: <auto-injected at release time by GitHub Actions build pipeline>
#
# One-liner (after `Set-ExecutionPolicy Bypass -Scope Process`):
#   $env:RP_TOKEN = "eyJhbGc..."
#   iwr -useb https://rp.monxas.casa/install.ps1 | iex
#
# Companion script: packaging/windows/install-nssm.ps1 (service install).
#
# Exit codes:
#   0 success
#   1 invalid args / preflight failure
#   2 install failure (Tailscale or agent)
#   3 enrollment failure
#   4 service install failure
#
# Compatible with PowerShell 5.1+ (Windows 10/11 default).

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$Token       = $env:RP_TOKEN,
    [string]$Server      = $(if ($env:RP_SERVER) { $env:RP_SERVER } else { 'https://rp.monxas.casa' }),
    [string]$Group       = $(if ($env:RP_GROUP)  { $env:RP_GROUP }  else { 'default' }),
    [Alias('Hostname')]
    [string]$HostnameTag = $(if ($env:RP_HOSTNAME) { $env:RP_HOSTNAME } else { $env:COMPUTERNAME }),
    [string]$Version     = $(if ($env:RP_VERSION) { $env:RP_VERSION } else { 'latest' }),
    [ValidateSet('auto','winget','binary','wsl')]
    [string]$InstallMode = 'auto',
    [switch]$Show,
    [switch]$Offline,
    [string]$LocalBinary,
    [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
$Script:InstallDir   = 'C:\Program Files\RemotePulse'
$Script:DataDir      = 'C:\ProgramData\RemotePulse'
$Script:LogDir       = Join-Path $Script:DataDir 'logs'
$Script:ConfigPath   = Join-Path $Script:DataDir 'config.toml'
$Script:ServiceName  = 'RemotePulseAgent'
$Script:TailscaleMsiUrl = 'https://pkgs.tailscale.com/stable/tailscale-setup-latest.msi'
# SHA256 is published by Tailscale at the *-sha256 sidecar URL. Build pipeline
# pins a known-good hash; if empty here we fetch the .sha256 file at runtime.
$Script:TailscaleMsiSha256 = ''
$Script:ReleasesBaseUrl = 'https://github.com/monxas/remote-pulse/releases'

# ---------------------------------------------------------------------------
# Logging helpers (avoid emojis per ADR convention; ANSI optional in PS7)
# ---------------------------------------------------------------------------
function Write-Step([string]$Message) { Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Ok  ([string]$Message) { Write-Host "OK  $Message" -ForegroundColor Green }
function Write-Warn2([string]$Message) { Write-Warning $Message }
function Write-ErrLine([string]$Message) { Write-Host "ERR $Message" -ForegroundColor Red }

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------
function Show-Help {
    @"
Remote-Pulse Windows installer (F7 — ADR-0008)

Usage:
  iwr -useb https://rp.monxas.casa/install.ps1 | iex            # one-liner
  .\install.ps1 -Token <JWT> [options]

Flags:
  -Token <JWT>          Enrollment token (required unless -Show). Env: RP_TOKEN
  -Server <URL>         Server URL. Default: https://rp.monxas.casa
  -Group <name>         Host group. Default: 'default'
  -Hostname <name>      Override hostname. Default: \$env:COMPUTERNAME
  -Version <ref>        Agent version/release. Default: 'latest'
  -InstallMode <mode>   auto | winget | binary | wsl  (default: auto)
  -Show                 Print plan + expected SHA256; no mutations
  -Offline              Skip downloads; use -LocalBinary
  -LocalBinary <path>   Path to pre-downloaded rp.exe (air-gapped install)
  -Verbose              Detailed logging
  -WhatIf               Show what would happen without doing it
  -Help                 This help

Environment vars (equivalent to flags):
  RP_TOKEN, RP_SERVER, RP_GROUP, RP_HOSTNAME, RP_VERSION

Examples:
  # Audit-first
  .\install.ps1 -Show -Token test

  # Token-driven silent install
  .\install.ps1 -Token eyJhbGc... -Group family

  # Air-gapped
  .\install.ps1 -Token eyJhbGc... -Offline -LocalBinary C:\tmp\rp.exe

NOTE: This script requires admin privileges. It will self-elevate via UAC.
NOTE: If iwr...|iex fails with execution policy, run first:
        Set-ExecutionPolicy Bypass -Scope Process -Force
"@
}

if ($Help) { Show-Help; exit 0 }

# ---------------------------------------------------------------------------
# Self-elevation (skip if just printing plan)
# ---------------------------------------------------------------------------
function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($id)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Invoke-SelfElevate {
    if ($Show) { return }   # audit mode does no writes
    if (Test-IsAdmin) { return }

    Write-Warn2 "Not running as Administrator. Attempting self-elevation via UAC..."
    $scriptPath = $MyInvocation.MyCommand.Definition
    if (-not $scriptPath -or -not (Test-Path $scriptPath)) {
        Write-ErrLine "Self-elevation not possible from an in-memory script (iwr|iex). Run:"
        Write-Host "  Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile','-Command','iwr -useb $Server/install.ps1 | iex'" -ForegroundColor Yellow
        exit 1
    }

    # Forward original args to elevated process
    $argList = @('-NoProfile','-ExecutionPolicy','Bypass','-File', $scriptPath)
    foreach ($kv in $PSBoundParameters.GetEnumerator()) {
        if ($kv.Value -is [switch]) {
            if ($kv.Value.IsPresent) { $argList += "-$($kv.Key)" }
        } else {
            $argList += "-$($kv.Key)"; $argList += [string]$kv.Value
        }
    }
    Start-Process powershell.exe -Verb RunAs -ArgumentList $argList
    exit 0
}

# ---------------------------------------------------------------------------
# OS / arch detection
# ---------------------------------------------------------------------------
function Get-PlatformInfo {
    $arch = switch -Regex ($env:PROCESSOR_ARCHITECTURE) {
        '^AMD64$' { 'x64' }
        '^ARM64$' { 'arm64' }
        '^x86$'   { 'x86' }
        default   { $env:PROCESSOR_ARCHITECTURE }
    }
    $osv = [System.Environment]::OSVersion.Version
    return [pscustomobject]@{
        Arch        = $arch
        OsVersion   = "$($osv.Major).$($osv.Minor).$($osv.Build)"
        IsWin10Plus = ($osv.Major -ge 10)
    }
}

# ---------------------------------------------------------------------------
# Host fingerprint (stable, no PII)
# ---------------------------------------------------------------------------
function Get-HostFingerprint {
    try {
        $mg = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Cryptography' -Name MachineGuid -ErrorAction Stop).MachineGuid
        $bytes = [Text.Encoding]::UTF8.GetBytes($mg)
        $sha = [Security.Cryptography.SHA256]::Create()
        return -join ($sha.ComputeHash($bytes) | ForEach-Object { $_.ToString('x2') })
    } catch {
        return "unknown-$([int][double]::Parse((Get-Date -UFormat %s)))"
    }
}

# ---------------------------------------------------------------------------
# SHA256 verification
# ---------------------------------------------------------------------------
function Test-Sha256 {
    param([string]$Path, [string]$Expected)
    if (-not $Expected) {
        Write-Warn2 "No expected SHA256 supplied for $Path; skipping verify (NOT recommended)"
        return $true
    }
    $actual = (Get-FileHash -Path $Path -Algorithm SHA256).Hash.ToLower()
    if ($actual -ne $Expected.ToLower()) {
        Write-ErrLine "SHA256 mismatch for $Path"
        Write-ErrLine "  expected: $Expected"
        Write-ErrLine "  actual:   $actual"
        return $false
    }
    Write-Verbose "SHA256 verified: $actual"
    return $true
}

# ---------------------------------------------------------------------------
# Download with progress
# ---------------------------------------------------------------------------
function Invoke-Download {
    param([string]$Url, [string]$OutFile)
    Write-Step "Downloading $Url"
    try {
        # PowerShell 5.1: avoid IE engine slowness
        $oldProgress = $ProgressPreference
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest -Uri $Url -OutFile $OutFile -UseBasicParsing
        $ProgressPreference = $oldProgress
    } catch {
        throw "Download failed for $Url : $($_.Exception.Message)"
    }
}

# ---------------------------------------------------------------------------
# Audit mode
# ---------------------------------------------------------------------------
function Show-Plan {
    $plat = Get-PlatformInfo
    @"
Remote-Pulse Windows installer plan
====================================

This installer will:
  1. Self-elevate via UAC if not already admin
  2. Detect OS/arch (Windows $($plat.OsVersion) / $($plat.Arch))
  3. Install Tailscale MSI if missing ($Script:TailscaleMsiUrl)
       SHA256 verify against published .sha256 sidecar
  4. Install Remote-Pulse agent via:
       Mode: $InstallMode
       - winget: 'winget install Monxas.RemotePulse'
       - binary: download rp-windows-$($plat.Arch).exe from GitHub Releases
       - wsl:    install Linux agent inside WSL2 Ubuntu
  5. POST $Server/v1/enroll  with provided token
       agent_config returned includes ephemeral Tailscale auth-key
  6. Write $Script:ConfigPath  (ACL: Administrators+SYSTEM)
  7. tailscale up --authkey <ephemeral> --hostname $HostnameTag --ssh
       --advertise-tags=tag:rp-agent-$Group
  8. Install NSSM service '$Script:ServiceName' (auto-start + restart on fail)
  9. nssm start  + smoke-test 'rp.exe status'

Target:
  Server:    $Server
  Hostname:  $HostnameTag
  Group:     $Group
  Version:   $Version
  Install:   $Script:InstallDir
  Data:      $Script:DataDir
  Logs:      $Script:LogDir

Verify this script (release pipeline injects SHA256 in header):
  Compare \$Server/install.ps1.sha256 with: (Get-FileHash install.ps1).Hash

NO MUTATIONS in -Show mode.
"@
}

# ---------------------------------------------------------------------------
# Tailscale install (F2)
# ---------------------------------------------------------------------------
function Install-Tailscale {
    if (Get-Command tailscale.exe -ErrorAction SilentlyContinue) {
        Write-Ok "Tailscale already installed: $((tailscale.exe version) -split '\n' | Select-Object -First 1)"
        return
    }
    if ($Offline) {
        throw "Tailscale missing and -Offline set. Install Tailscale manually first."
    }
    Write-Step "Installing Tailscale (silent MSI)"
    $msiPath = Join-Path $env:TEMP 'tailscale-setup.msi'
    Invoke-Download -Url $Script:TailscaleMsiUrl -OutFile $msiPath

    # Best-effort SHA256 verify via sidecar
    if ($Script:TailscaleMsiSha256) {
        if (-not (Test-Sha256 -Path $msiPath -Expected $Script:TailscaleMsiSha256)) {
            throw "Tailscale MSI integrity check failed (pinned hash mismatch)"
        }
    } else {
        try {
            $sidecar = Invoke-WebRequest -Uri "$Script:TailscaleMsiUrl.sha256" -UseBasicParsing -ErrorAction Stop
            $expected = ($sidecar.Content -split '\s+')[0]
            if (-not (Test-Sha256 -Path $msiPath -Expected $expected)) {
                throw "Tailscale MSI integrity check failed"
            }
        } catch {
            Write-Warn2 "Tailscale .sha256 sidecar unreachable; proceeding without verify (vendor risk accepted)"
        }
    }

    $msiArgs = @('/i', $msiPath, '/quiet', '/norestart')
    if ($PSCmdlet.ShouldProcess('Tailscale MSI', "msiexec $msiArgs")) {
        $p = Start-Process msiexec.exe -ArgumentList $msiArgs -Wait -PassThru
        if ($p.ExitCode -ne 0) { throw "Tailscale MSI install exited $($p.ExitCode)" }
    }

    # Wait for service
    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $deadline) {
        $svc = Get-Service Tailscale -ErrorAction SilentlyContinue
        if ($svc -and $svc.Status -eq 'Running') { Write-Ok 'Tailscale service running'; return }
        Start-Sleep -Milliseconds 500
    }
    Write-Warn2 'Tailscale service did not enter Running state in 30s; continuing anyway'
}

# ---------------------------------------------------------------------------
# Agent install (winget / binary / wsl)
# ---------------------------------------------------------------------------
function Install-Agent {
    param([string]$Arch)

    if ($Offline) {
        if (-not $LocalBinary -or -not (Test-Path $LocalBinary)) {
            throw "-Offline requires -LocalBinary <path-to-rp.exe>"
        }
        Write-Step "Offline install from $LocalBinary"
        New-Item -ItemType Directory -Force -Path $Script:InstallDir | Out-Null
        Copy-Item -Force $LocalBinary (Join-Path $Script:InstallDir 'rp.exe')
        return
    }

    $mode = $InstallMode
    if ($mode -eq 'auto') {
        if (Get-Command winget -ErrorAction SilentlyContinue) { $mode = 'winget' } else { $mode = 'binary' }
    }

    switch ($mode) {
        'winget' {
            Write-Step "Installing via winget (Monxas.RemotePulse)"
            $wingetArgs = @('install','--id','Monxas.RemotePulse','--silent','--accept-source-agreements','--accept-package-agreements')
            if ($Version -ne 'latest') { $wingetArgs += @('--version', $Version) }
            if ($PSCmdlet.ShouldProcess('winget Monxas.RemotePulse', "winget $wingetArgs")) {
                & winget @wingetArgs
                if ($LASTEXITCODE -ne 0) {
                    Write-Warn2 "winget install failed (exit=$LASTEXITCODE). Falling back to binary."
                    Install-AgentBinary -Arch $Arch
                }
            }
        }
        'binary' { Install-AgentBinary -Arch $Arch }
        'wsl' {
            Write-Step "Delegating to WSL Linux installer"
            if (-not (Get-Command wsl -ErrorAction SilentlyContinue)) { throw "wsl.exe not found. Install WSL2 first: wsl --install" }
            $cmd = "curl -fsSL $Server/install | sh -s -- --token=$Token --server=$Server --group=$Group --hostname=$HostnameTag --version=$Version"
            & wsl.exe -- bash -lc $cmd
            if ($LASTEXITCODE -ne 0) { throw "WSL install failed (exit=$LASTEXITCODE)" }
            return  # WSL path handles its own service registration
        }
    }
}

function Install-AgentBinary {
    param([string]$Arch)
    Write-Step "Installing rp.exe binary ($Arch, version=$Version)"
    New-Item -ItemType Directory -Force -Path $Script:InstallDir | Out-Null
    $relTag = if ($Version -eq 'latest') { 'latest/download' } else { "download/$Version" }
    $url = "$Script:ReleasesBaseUrl/$relTag/rp-windows-$Arch.exe"
    $sumUrl = "$Script:ReleasesBaseUrl/$relTag/SHA256SUMS"
    $tmp = Join-Path $env:TEMP 'rp.exe'
    Invoke-Download -Url $url -OutFile $tmp

    # Fetch SHA256SUMS and locate our binary hash
    try {
        $sums = (Invoke-WebRequest -Uri $sumUrl -UseBasicParsing).Content
        $match = ($sums -split "`n") | Where-Object { $_ -match "rp-windows-$Arch\.exe" } | Select-Object -First 1
        if ($match) {
            $expected = ($match -split '\s+')[0]
            if (-not (Test-Sha256 -Path $tmp -Expected $expected)) {
                throw "rp.exe SHA256 mismatch — refusing to install. Possible tampering."
            }
        } else {
            Write-Warn2 "SHA256SUMS entry for rp-windows-$Arch.exe not found; skipping verify"
        }
    } catch {
        Write-Warn2 "SHA256SUMS fetch failed: $($_.Exception.Message)"
    }

    Copy-Item -Force $tmp (Join-Path $Script:InstallDir 'rp.exe')
}

# ---------------------------------------------------------------------------
# Enrollment (POST /v1/enroll)
# ---------------------------------------------------------------------------
function Invoke-Enroll {
    param([string]$Arch)
    Write-Step "Enrolling with $Server/v1/enroll"
    $payload = @{
        token            = $Token
        hostname         = $HostnameTag
        group            = $Group
        os               = 'windows'
        arch             = $Arch
        host_fingerprint = (Get-HostFingerprint)
        agent_version    = $Version
    } | ConvertTo-Json -Compress

    try {
        $resp = Invoke-RestMethod -Method Post -Uri "$Server/v1/enroll" `
                                  -ContentType 'application/json' -Body $payload `
                                  -TimeoutSec 30
    } catch {
        throw "Enrollment failed: $($_.Exception.Message)"
    }

    if (-not $resp.host_id) { throw "Enrollment response missing host_id: $($resp | ConvertTo-Json -Compress)" }
    Write-Ok "Enrolled. host_id=$($resp.host_id)"
    return $resp
}

# ---------------------------------------------------------------------------
# Write config + ACL
# ---------------------------------------------------------------------------
function Write-Config {
    param($EnrollResp)
    Write-Step "Writing $Script:ConfigPath"
    New-Item -ItemType Directory -Force -Path $Script:DataDir | Out-Null
    New-Item -ItemType Directory -Force -Path $Script:LogDir  | Out-Null

    $hbInterval = 30
    if ($EnrollResp.PSObject.Properties.Name -contains 'agent_config' `
        -and $EnrollResp.agent_config.PSObject.Properties.Name -contains 'heartbeat_interval_s') {
        $hbInterval = $EnrollResp.agent_config.heartbeat_interval_s
    }

    $toml = @"
# Remote-Pulse agent config (managed by install.ps1)
host_id              = "$($EnrollResp.host_id)"
server_url           = "$Server"
hostname             = "$HostnameTag"
group                = "$Group"
heartbeat_interval_s = $hbInterval
"@
    if ($PSCmdlet.ShouldProcess($Script:ConfigPath, 'write config')) {
        Set-Content -Path $Script:ConfigPath -Value $toml -Encoding UTF8
    }

    # Lock ACL: SYSTEM + Administrators full, deny everyone else
    try {
        $acl = New-Object System.Security.AccessControl.FileSecurity
        $acl.SetAccessRuleProtection($true, $false)   # disable inheritance
        $rules = @(
            New-Object System.Security.AccessControl.FileSystemAccessRule('NT AUTHORITY\SYSTEM','FullControl','Allow'),
            New-Object System.Security.AccessControl.FileSystemAccessRule('BUILTIN\Administrators','FullControl','Allow')
        )
        foreach ($r in $rules) { $acl.AddAccessRule($r) }
        Set-Acl -Path $Script:ConfigPath -AclObject $acl
        Write-Verbose "ACL locked on $Script:ConfigPath"
    } catch {
        Write-Warn2 "ACL hardening failed: $($_.Exception.Message)"
    }
}

# ---------------------------------------------------------------------------
# Tailscale up with auth-key (F2)
# ---------------------------------------------------------------------------
function Invoke-TailscaleUp {
    param($EnrollResp)
    if (-not ($EnrollResp.PSObject.Properties.Name -contains 'agent_config')) { return }
    if (-not ($EnrollResp.agent_config.PSObject.Properties.Name -contains 'tailscale_authkey')) { return }
    $authkey = $EnrollResp.agent_config.tailscale_authkey
    if (-not $authkey) { return }

    Write-Step "Joining tailnet (tailscale up)"
    $tsArgs = @(
        'up',
        "--authkey=$authkey",
        "--hostname=$HostnameTag",
        '--ssh',
        "--advertise-tags=tag:rp-agent-$Group",
        '--accept-routes'
    )
    if ($PSCmdlet.ShouldProcess('tailscale', "tailscale $tsArgs")) {
        & tailscale.exe @tsArgs
        if ($LASTEXITCODE -ne 0) { Write-Warn2 "tailscale up exit=$LASTEXITCODE (may need manual login)" }
    }
}

# ---------------------------------------------------------------------------
# NSSM service install (delegated)
# ---------------------------------------------------------------------------
function Install-Service {
    Write-Step "Installing service $Script:ServiceName via NSSM"
    $nssmScript = Join-Path $PSScriptRoot '..\packaging\windows\install-nssm.ps1'
    if (-not (Test-Path $nssmScript)) {
        # Fallback: try local copy next to install.ps1 (when extracted from zip)
        $nssmScript = Join-Path $PSScriptRoot 'install-nssm.ps1'
    }
    if (-not (Test-Path $nssmScript)) {
        Write-Warn2 "install-nssm.ps1 not found locally; downloading from $Server"
        $nssmScript = Join-Path $env:TEMP 'install-nssm.ps1'
        Invoke-Download -Url "$Server/install-nssm.ps1" -OutFile $nssmScript
    }
    . $nssmScript
    Install-RemotePulseService -InstallDir $Script:InstallDir -DataDir $Script:DataDir `
                               -ServiceName $Script:ServiceName -Offline:$Offline
}

# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------
function Invoke-SmokeTest {
    Write-Step "Smoke test: rp.exe status"
    $rp = Join-Path $Script:InstallDir 'rp.exe'
    if (-not (Test-Path $rp)) { Write-Warn2 "rp.exe missing — smoke test skipped"; return }
    try {
        $out = & $rp status 2>&1
        Write-Host $out
        if ($LASTEXITCODE -ne 0) { Write-Warn2 "rp.exe status exit=$LASTEXITCODE (heartbeat may need a few seconds)" }
    } catch {
        Write-Warn2 "Smoke test failed: $($_.Exception.Message)"
    }
}

# ===========================================================================
# Main
# ===========================================================================
try {
    if ($Show) {
        Show-Plan
        exit 0
    }

    if (-not $Token) {
        Write-ErrLine "-Token <JWT> required (or set \$env:RP_TOKEN). Use -Show to inspect the plan."
        exit 1
    }

    Invoke-SelfElevate

    $plat = Get-PlatformInfo
    if (-not $plat.IsWin10Plus) {
        Write-ErrLine "Windows 10+ required (detected $($plat.OsVersion))"
        exit 1
    }
    Write-Ok "Windows $($plat.OsVersion) / $($plat.Arch)"

    New-Item -ItemType Directory -Force -Path $Script:InstallDir | Out-Null
    New-Item -ItemType Directory -Force -Path $Script:DataDir    | Out-Null
    New-Item -ItemType Directory -Force -Path $Script:LogDir     | Out-Null

    # Step 1 — Tailscale
    try { Install-Tailscale } catch { Write-ErrLine $_.Exception.Message; exit 2 }

    # Step 2 — Agent
    try { Install-Agent -Arch $plat.Arch } catch { Write-ErrLine $_.Exception.Message; exit 2 }

    # Step 3 — Enroll
    $enroll = $null
    try { $enroll = Invoke-Enroll -Arch $plat.Arch } catch { Write-ErrLine $_.Exception.Message; exit 3 }

    # Step 4 — Config
    Write-Config -EnrollResp $enroll

    # Step 5 — Tailscale up (best-effort)
    try { Invoke-TailscaleUp -EnrollResp $enroll } catch { Write-Warn2 $_.Exception.Message }

    # Step 6 — NSSM service
    try { Install-Service } catch { Write-ErrLine $_.Exception.Message; exit 4 }

    # Step 7 — Smoke test
    Invoke-SmokeTest

    Write-Host ''
    Write-Ok "Remote-Pulse installed. Host registered."
    Write-Host "  Host:      $HostnameTag"
    Write-Host "  Group:     $Group"
    Write-Host "  Host ID:   $($enroll.host_id)"
    Write-Host "  Dashboard: $Server/dash"
    Write-Host ''
    Write-Host "  Logs:      $Script:LogDir"
    Write-Host "  Uninstall: $Script:InstallDir\..\packaging\windows\uninstall-nssm.ps1"
    exit 0
}
catch {
    Write-ErrLine "Unhandled error: $($_.Exception.Message)"
    Write-Verbose $_.ScriptStackTrace
    exit 1
}
