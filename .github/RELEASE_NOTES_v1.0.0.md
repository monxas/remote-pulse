# Remote-Pulse v1.0.0 — General Availability

First production release of Remote-Pulse, built end-to-end via parallel sub-agent orchestration over a single intensive session. See [ADR-0008](https://docs.monxas.casa/architecture/adr/ADR-0008-remote-pulse/) for full architectural design.

## What is Remote-Pulse?

Single-pane-of-glass fleet monitoring and remote control over Tailscale. One-command onboarding for any Linux/macOS/Windows host.

- **Single dashboard** for every machine you own (homelab, family laptops, client servers) with live sparklines for CPU, memory, disk, network.
- **One-command install** that handles Tailscale onboarding, SSH key exchange, and service registration in under 60 seconds.
- **Centralised SSH key lifecycle** — declarative groups, audit log, instant revocation.
- **Remote shell + screen** (Tailscale SSH, RustDesk Direct IP, Sunshine for GPU hosts) over WireGuard, P2P.
- **Defense-in-depth security**: agent-side local-approval gates so that a compromised server cannot escalate to destructive ops without human Telegram approval.

## Installation

### Linux / macOS (one-liner)

```sh
curl -fsSL https://rp.monxas.casa/install | sh -s -- --token=<JWT>
```

Inspect the script first:

```sh
curl -fsSL https://rp.monxas.casa/install?show=1
```

### Windows (winget)

```powershell
winget install Monxas.RemotePulse
rp install --token=<JWT>
```

### Manual installation

Download binaries from [GitHub Releases](https://github.com/monxas/remote-pulse/releases/v1.0.0):

- **Linux x64:** `rp-linux-x64`
- **Linux arm64:** `rp-linux-arm64`
- **macOS Intel:** `rp-macos-x64`
- **macOS Apple Silicon:** `rp-macos-arm64`
- **Windows x64:** `rp-windows-x64.exe`

Verify authenticity:

```sh
# Download SHA256SUMS and signature
curl -fsSL https://github.com/monxas/remote-pulse/releases/download/v1.0.0/SHA256SUMS -o SHA256SUMS
curl -fsSL https://github.com/monxas/remote-pulse/releases/download/v1.0.0/SHA256SUMS.sig -o SHA256SUMS.sig

# Verify checksum
sha256sum -c SHA256SUMS --ignore-missing

# Verify cosign signature (keyless OIDC)
cosign verify-blob \
  --certificate-identity=https://github.com/monxas/remote-pulse/.github/workflows/release.yml@refs/heads/main \
  --certificate-oidc-issuer=https://token.actions.githubusercontent.com \
  --signature SHA256SUMS.sig \
  SHA256SUMS
```

## What's Included (F1-F8)

### F1 — Foundation
- Agent CLI `rp` (Python 3.12): install, register, heartbeat daemon, status, version, uninstall
- Cross-OS metric collection (psutil)
- FastAPI server: enrollment, heartbeat ingestion, host inventory, JWT auth
- Postgres 16 + Alembic migrations
- systemd/launchd/NSSM service auto-registration

### F2 — Tailscale Integration
- Tailscale identity middleware (reads `Tailscale-User-Login` headers)
- Server emits ephemeral auth-keys via Tailscale API on enrollment
- `/v1/agent/reauth` endpoint for DR scenarios

### F3 — Observability + TUI
- TimescaleDB hypertables (90d heartbeats, 30d raw metrics + 1y aggregated)
- `/v1/metrics/{host}/sparkline` endpoint with smart bucket selection
- TUI dashboard `rp dash` (Textual + textual-plotext): 3-pane layout, 6 sparklines per host

### F4 — Security: SSH Lifecycle + Defense-in-Depth
- Ed25519 keygen + registration + sync via `rp keys` CLI
- Declarative `groups.yml` config + JSON Schema validation
- Server signing of remote commands (ed25519 cryptography)
- Agent TOFU trust anchor (`/etc/rp/server_pubkey.pem`)
- Local-approval enforcement: flag files with TTL (24h default), default-deny
- Telegram approval flow for destructive ops (prod/iarq groups)

### F5 — Multi-User + Web Dashboard
- PocketID OIDC integration (forward_auth via Caddy)
- Role-based access: admin/operator/viewer + accessible_groups filtering
- HTMX web dashboard with uPlot sparklines (Pico.css)
- Prometheus `/metrics` endpoint (14 metric families)
- Grafana dashboard JSON provisioned (17 panels)
- Magic-link enrollment flow with QR codes

### F6 — Remote Control
- `rp ssh <host>`: Tailscale SSH preferred, classic SSH fallback
- `rp screen <host>`: RustDesk Direct IP (default), Sunshine (Windows GPU), VNC (Linux fallback)
- `rp exec <host|@group>`: audited via signed commands API
- `rp install-screen` for installing RustDesk/Sunshine/VNC clients

### F7 — Distribution
- GitHub Actions multi-OS PyInstaller release matrix (Linux x64/arm64, macOS x64/arm64, Windows x64)
- winget-pkgs manifest (Monxas.RemotePulse)
- install.ps1 PowerShell with self-elevation + Tailscale MSI install
- Caddy public routing: `rp.monxas.casa` (install + enrollment) + `dash.rp.monxas.casa` (web dashboard)
- MkDocs Material public docs site (25 pages)

### F8 — Hardening
- Tailscale ACL policy.hujson (5 tags + 3 groups + 8 validation tests)
- pg_dump daily backup (systemd timer 03:00) + NAS sync + 30d retention
- DR drill procedure (quarterly cadence, RTO 10min target)
- API compatibility handshake (Sec-RP-* headers, 426 enforcement, N-2 deprecation)
- Canary deploy + N-1 binary auto-rollback (90s self-check timeout)
- Security review: trufflehog, semgrep, bandit, safety, cosign keyless OIDC signing
- Dependabot weekly dep updates

## Stats

- 30+ git commits, ~10,000+ lines added across 3 repos
- 200+ tests across server + agent
- 36+ server endpoints
- 8 implementation phases F1-F8 completed end-to-end

## Known Limitations

- Windows binary unsigned (SmartScreen warnings expected pre v2.0 with EV cert)
- Sunshine pairing remains one-time manual (PIN exchange limitation)
- PocketID OIDC client config required manually (not yet Ansible-provisioned)
- Telegram bot setup required manually
- Tailscale ACL apply requires admin web UI or API key

## Documentation

- **Public docs:** [rp.monxas.casa/docs](https://rp.monxas.casa/docs)
- **Architecture:** [ADR-0008](https://docs.monxas.casa/architecture/adr/ADR-0008-remote-pulse/)
- **Changelog:** [CHANGELOG.md](https://github.com/monxas/remote-pulse/blob/main/docs/docs/changelog.md)
- **Security:** [SECURITY.md](https://github.com/monxas/remote-pulse/blob/main/SECURITY.md)

## Acknowledgements

Built via parallel sub-agent orchestration with Claude Opus 4.7 (1M ctx). Devil's advocate critical review applied in-place to ADR-0008, resulting in 13 design changes including:

- Eliminated tsnet sidecar Go in favor of tailscaled+serve
- Deferred RustDesk hbbs/hbbr server (P2P Direct IP sufficient for tailnet peers)
- Added agent-side local-approval as defense-in-depth against server compromise
- Recalibrated 33d/9-10wk realistic effort vs 29d/6-8wk initial estimate

## Next Steps

1. **Install on your first host:** Follow the one-liner above
2. **Join the Tailscale tailnet:** Agent will guide you through onboarding
3. **Access the dashboard:** TUI via `rp dash` or web at `dash.rp.monxas.casa`
4. **Configure SSH keys:** `rp keys init && rp keys sync`
5. **Try remote control:** `rp ssh <host>` or `rp screen <host>`

## Support

- **Issues:** [GitHub Issues](https://github.com/monxas/remote-pulse/issues)
- **Discussions:** [GitHub Discussions](https://github.com/monxas/remote-pulse/discussions)
- **Security:** Report via [SECURITY.md](https://github.com/monxas/remote-pulse/blob/main/SECURITY.md)

---

**Maintainer:** [@monxas](https://github.com/monxas)  
**License:** Apache-2.0
