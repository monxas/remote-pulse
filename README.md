# Remote-Pulse

> Single-pane-of-glass fleet monitoring and remote control over Tailscale. One-command onboarding for any Linux/macOS/Windows host.

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Status](https://img.shields.io/badge/status-pre--alpha-orange.svg)]()
[![CI](https://github.com/monxas/remote-pulse/workflows/CI/badge.svg)](https://github.com/monxas/remote-pulse/actions/workflows/ci.yml)
[![Release](https://github.com/monxas/remote-pulse/workflows/release/badge.svg)](https://github.com/monxas/remote-pulse/releases/latest)

**Status:** Pre-alpha / F1 in progress. ADR-0008 [accepted internally](https://docs.monxas.casa/architecture/adr/ADR-0008-remote-pulse/) (homelab docs).

## What is this

Remote-Pulse is an agent + server platform that gives you:

- **Single dashboard** for every machine you own (homelab, family laptops, client servers) with live sparklines for CPU, memory, disk, network.
- **One-command install** that handles Tailscale onboarding, SSH key exchange, and service registration in under 60 seconds.
- **Centralised SSH key lifecycle** — declarative groups, audit log, instant revocation.
- **Remote shell + screen** (Tailscale SSH, RustDesk Direct IP, Sunshine for GPU hosts) over WireGuard, P2P.
- **Defense-in-depth security**: agent-side local-approval gates so that a compromised server cannot escalate to destructive ops in `prod`/`iarq` groups without human Telegram approval.

This repo contains the **public agent + CLI**. The server lives privately in the homelab; details in ADR-0008.

## Install

### Method 1: One-liner (Linux / macOS)

The quickest way to get started. Installs agent, registers with server, and sets up systemd/launchd service:

```sh
curl -fsSL https://rp.monxas.casa/install | sh -s -- --token=<JWT>
```

Inspect the script before running (recommended):

```sh
curl -fsSL https://rp.monxas.casa/install?show=1
```

### Method 2: winget (Windows)

For Windows users, install via winget (once published to microsoft/winget-pkgs):

```powershell
winget install Monxas.RemotePulse
```

Then register the agent:

```powershell
rp install --token=<JWT>
```

### Method 3: pipx (Python users)

If you have Python 3.12+ and want auto-updates:

```sh
pipx install remote-pulse
rp install --token=<JWT>
```

Upgrade to latest version:

```sh
pipx upgrade remote-pulse
```

### Method 4: Download binary (manual)

Download the latest binary for your platform from [GitHub Releases](https://github.com/monxas/remote-pulse/releases/latest):

- **Linux x64:** `rp-linux-x64`
- **Linux arm64:** `rp-linux-arm64`
- **macOS Intel:** `rp-macos-x64`
- **macOS Apple Silicon:** `rp-macos-arm64`
- **Windows x64:** `rp-windows-x64.exe`

Verify the download:

```sh
# Download SHA256SUMS from the release
curl -fsSL https://github.com/monxas/remote-pulse/releases/latest/download/SHA256SUMS -o SHA256SUMS

# Verify (Linux/macOS)
sha256sum -c SHA256SUMS --ignore-missing

# Verify (Windows PowerShell)
Get-FileHash rp-windows-x64.exe -Algorithm SHA256
```

Then install manually:

```sh
# Linux/macOS
chmod +x rp-linux-x64
./rp-linux-x64 install --token=<JWT>

# Windows
.\rp-windows-x64.exe install --token=<JWT>
```

## Architecture (one paragraph)

Agents are Python 3.12 + uv, distributed as PyInstaller binaries or `pipx`. They speak to a FastAPI server (private, in a homelab LXC) over a multi-channel WebSocket riding on Tailscale (`tailscaled` + `tailscale serve` injects identity headers). Postgres 16 + TimescaleDB stores fleet state and an immutable audit log. Web dashboard (HTMX + uPlot), TUI dashboard (Textual + textual-plotext), and Grafana panels read from the same data layer.

Full design rationale, alternatives considered, security model and DR procedure live in **ADR-0008** ([public copy](https://docs.monxas.casa/architecture/adr/ADR-0008-remote-pulse/)).

## Repo layout

```
monxas-remote-pulse/
├── agent/         # rp Python CLI + daemon (installable as `pipx install remote-pulse`)
├── server/        # FastAPI + Postgres + Alembic (deployed via Ansible role privately)
├── scripts/       # install.sh, install.ps1, uninstall.sh
├── packaging/     # systemd unit / launchd plist / NSSM service stubs
├── docs/          # MkDocs site (rp.monxas.casa/docs after F7)
└── tests/         # integration tests (per-component tests live alongside code)
```

## Status / roadmap

See [ADR-0008](https://docs.monxas.casa/architecture/adr/ADR-0008-remote-pulse/) for the full 8-phase plan. Short version:

- **F1** (in progress) — Agent MVP + server stub over LAN HTTP
- **F2** — Tailscale daemon + `tailscale serve` + JWT enrollment
- **F3** — TUI dashboard with sparklines (`textual-plotext`)
- **F4** — SSH key lifecycle + remote exec + local-approval enforcement
- **F5** — Web dashboard + Grafana panels + multi-user (PocketID OIDC)
- **F6** — Tailscale SSH + RustDesk Direct IP + Sunshine
- **F7** — One-liner public + Windows winget + docs site
- **F8** — Hardening, DR drill, API compat policy, v1.0.0 GA

## Development

### Testing GitHub Actions locally

You can test workflows locally using [act](https://github.com/nektos/act):

```sh
# Install act (macOS)
brew install act

# Test CI workflow
act pull_request

# Test release workflow (requires tag)
act push --eventpath <(echo '{"ref": "refs/tags/v0.1.0"}')

# List available workflows
act -l
```

Note: The release workflow requires large runners for cross-platform builds. Local testing with act may not exactly match GitHub Actions behavior, especially for QEMU-based arm64 builds.

### Building binaries locally

```sh
cd agent

# Build for your current platform
make build-binary

# The binary will be in: dist/rp (or dist/rp.exe on Windows)

# Run tests
make test

# Lint code
make lint

# Clean artifacts
make clean
```

## Contributing

Pre-alpha. Issues welcome; PRs deferred until v0.2 surface stabilises.

## License

Apache-2.0. See [LICENSE](./LICENSE).

---

**Maintainer:** [@monxas](https://github.com/monxas)
**Built with:** [Claude Code](https://claude.com/claude-code) as pair-programmer.
