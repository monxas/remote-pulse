# Remote-Pulse bootstrap scripts

Ticket **F1-4 (ADR-0008)**. Phase F1 only — Tailscale (F2), SSH keys (F4) and
PyInstaller binaries (F7) are intentionally **not** wired up yet; TODO markers
in the scripts call them out where they will plug in.

## Layout

```
scripts/
├── install.sh          # Bootstrap installer (Linux/macOS, POSIX sh)
├── install.ps1         # Windows stub (full impl in F7)
├── uninstall.sh        # Tear-down (also reachable as `rp uninstall`)
├── lib/
│   ├── detect-os.sh    # detect_os/arch/distro/init_system/pkg_manager
│   ├── install-python.sh  # ensure_python_312 via apt/dnf/brew/apk
│   └── install-uv.sh   # ensure_uv (official installer + version check)
└── README.md           # this file
```

## What `install.sh` does (F1 scope)

1. Parse flags / env (`--token`, `--server`, `--group`, `--hostname`,
   `--version`, `--show`).
2. Detect OS + arch (via `lib/detect-os.sh`).
3. Ensure Python 3.12 (via `lib/install-python.sh`).
4. Ensure `uv` (via `lib/install-uv.sh`).
5. `uv tool install remote-pulse` — from GitHub if reachable, falling back to
   the local dev path `/Users/ramonkamibayashicarrera/monxas-remote-pulse/agent`.
6. `POST $RP_SERVER/v1/enroll` with the enrollment JWT, parse `host_id`.
7. Write `/etc/rp/config.toml` (`root:root` `0600`) + create `/var/lib/rp/`.
8. Hand off to `packaging/install-systemd.sh` or `packaging/install-launchd.sh`
   to register and start the service unit.

### Audit-first usage

```sh
sh install.sh --show
```

Prints the full plan, target server, detected OS/arch, and the SHA256
placeholder. No mutations.

### Silent install

```sh
sh install.sh --token=eyJhbGc... --group=family --server=http://192.168.0.X:8080
```

### Override env-style

```sh
RP_TOKEN=eyJ... RP_GROUP=prod sh install.sh
```

## Uninstall

```sh
sh uninstall.sh --confirm
# or, once the agent CLI is installed:
rp uninstall --confirm
```

Removes service unit, `/etc/rp/`, `/var/lib/rp/`, and the `remote-pulse` uv
tool. Use `--keep-tool` to preserve the binary for re-enrollment.

## Conventions

- **POSIX sh only** — runs under `bash`, `dash`, `ash`, `busybox sh`. No
  `[[`, no arrays, no `local`, no process substitution.
- `set -eu` at the top of every executable script.
- Errors go to stderr with a clear prefix, non-zero exit codes.
- Idempotent: re-running on an already-installed host updates in place.
- `lib/*.sh` files are sourced, never executed; their functions print one
  token to stdout and never call `exit`.

## Windows (`install.ps1`) — F7 scope

PowerShell 5.1+ bootstrap. Lives at `scripts/install.ps1`, delegates service
install to `packaging/windows/install-nssm.ps1`.

### One-liner

```powershell
# Open an elevated PowerShell, then:
Set-ExecutionPolicy Bypass -Scope Process -Force
$env:RP_TOKEN = "eyJhbGc..."
iwr -useb https://rp.monxas.casa/install.ps1 | iex
```

If launched from a non-elevated shell, `install.ps1` **self-elevates via UAC**
(triggers a consent prompt). When run via `iwr | iex` (in-memory), self-elevation
is impossible — the script prints the explicit `Start-Process -Verb RunAs` line
to copy-paste.

### Audit first (recommended)

```powershell
iwr -useb https://rp.monxas.casa/install.ps1 -OutFile install.ps1
iwr -useb https://rp.monxas.casa/install.ps1.sha256 -OutFile install.ps1.sha256
# Verify before running:
$expected = (Get-Content install.ps1.sha256).Split(' ')[0]
$actual   = (Get-FileHash install.ps1 -Algorithm SHA256).Hash.ToLower()
if ($expected -ne $actual) { throw 'HASH MISMATCH — abort' }

.\install.ps1 -Show -Token test    # print plan, no mutations
```

### Flag reference

| Flag | Default | Description |
|------|---------|-------------|
| `-Token <JWT>` | `$env:RP_TOKEN` | Enrollment token (required unless `-Show`) |
| `-Server <URL>` | `https://rp.monxas.casa` | Server URL |
| `-Group <name>` | `default` | Host group |
| `-Hostname <name>` | `$env:COMPUTERNAME` | Override registered hostname |
| `-Version <ref>` | `latest` | Agent release tag |
| `-InstallMode <m>` | `auto` | `winget` \| `binary` \| `wsl` \| `auto` |
| `-Show` | off | Print plan + exit 0 |
| `-Offline` | off | Skip downloads (requires `-LocalBinary`) |
| `-LocalBinary <p>` | — | Path to pre-staged `rp.exe` |
| `-Verbose` | off | Detailed logging |
| `-WhatIf` | off | Dry-run mode (no mutations) |
| `-Help` | off | Show help |

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Invalid args / preflight failure |
| 2 | Tailscale or agent install failure |
| 3 | Enrollment failure (`POST /v1/enroll`) |
| 4 | NSSM service install failure |

### Common errors

**`File install.ps1 cannot be loaded because running scripts is disabled`**

Run once in the same PowerShell session:

```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force
```

This bypasses ExecutionPolicy only for the current process — no permanent change.

**`Invoke-WebRequest : The underlying connection was closed: Could not establish trust relationship for the SSL/TLS secure channel.`**

PowerShell 5.1 defaults to TLS 1.0/1.1. Add before retry:

```powershell
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
```

**`'winget' is not recognized`**

Either install **App Installer** from the Microsoft Store, or force binary path:

```powershell
.\install.ps1 -Token ... -InstallMode binary
```

**`Windows protected your PC` (SmartScreen) when launching `rp.exe`**

See `packaging/windows/README.md` § *Windows Defender + SmartScreen
troubleshooting* for Defender exclusions, false-positive reporting, and the
EV code signing roadmap.

**Self-elevation loop / UAC denied**

Run `install.ps1` from an already-elevated PowerShell (right-click *Run as
administrator*) rather than via `iwr | iex`.

### Air-gapped install

```powershell
# Pre-stage on a USB stick:
#   rp.exe                  (from GitHub Releases on internet host)
#   nssm.exe                (extract from nssm-2.24.zip, win64 subdir)
#   tailscale-setup.msi     (pre-installed manually on target)

.\install.ps1 -Token eyJhbGc... -Offline -LocalBinary E:\rp.exe
```

The enrollment POST still needs to reach `$Server`. For fully isolated
deployments, use the `rp enroll --offline` flow (F4 phase TODO).

## TODO markers (later phases)

| Phase | Where | What |
|-------|-------|------|
| F2 | `install.sh` step 4 | Server returns Tailscale auth-key; install + join tailnet. |
| F2 | `install.sh` step 4 | Switch default `RP_SERVER` to `https://rp.monxas.casa`. |
| F4 | `install.sh` post-enroll | Generate ed25519 keypair; push pubkey to server. |
| F4 | `uninstall.sh` | Call `/v1/keys/revoke` before deleting `/var/lib/rp`. |
| F7 | `install.sh` step 3 | Replace `uv tool install` with PyInstaller binary download + SHA256 verify against `$RP_SERVER/install.sha256`. |
| F7 | `install.ps1` | **DONE** — winget + PyInstaller `.exe` + NSSM service. |
| F7 | build pipeline | Inject SHA256 of published `install.sh` / `install.ps1` into header comment. |
| F7 | winget-pkgs | Submit `Monxas.RemotePulse` manifest to `microsoft/winget-pkgs`. |
