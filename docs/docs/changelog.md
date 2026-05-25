# Changelog

All notable changes to Remote-Pulse will be documented here. Format
follows [Keep a Changelog](https://keepachangelog.com).

## [1.0.0] - 2026-05-25

First general availability release. Built end-to-end via parallel sub-agent
orchestration over a single intensive session. See ADR-0008 for full design.

### Added

#### F1 — Foundation
- Agent CLI `rp` (Python 3.12, Click): install, register, heartbeat (daemon),
  status, version, uninstall, with cross-OS metric collection (psutil).
- FastAPI server: enrollment, heartbeat ingestion, host inventory, JWT auth
  tokens (HS512, single-use, TTL 24h).
- Postgres 16 + Alembic migrations.
- POSIX bootstrap install.sh with --show audit mode.
- systemd unit (Linux), launchd plist (macOS), NSSM service (Windows).

#### F2 — Tailscale Integration
- Tailscale identity middleware (reads Tailscale-User-Login headers).
- Server emits ephemeral auth-keys via Tailscale API on enrollment.
- /v1/agent/reauth endpoint for DR scenarios.

#### F3 — Observability + TUI
- TimescaleDB hypertables (heartbeats 90d retention, metric_samples 30d raw +
  1y aggregated 5min).
- /v1/metrics/{host}/sparkline endpoint with smart bucket selection.
- TUI dashboard `rp dash` (Textual + textual-plotext): 3-pane layout,
  6 real sparklines per host, color-coded status, 2s auto-refresh.

#### F4 — Security: SSH Lifecycle + Defense-in-Depth
- Schema: ssh_keys, groups (with TEXT[] access_users), commands (append-only
  audit log with Postgres trigger + Python __setattr__ guard), agent_versions.
- 4 seed groups (default, prod, family, iarq).
- Agent ed25519 keygen + registration + sync via `rp keys` CLI.
- Declarative groups.yml config + JSON Schema validation.
- Ed25519 server signing of remote commands (cryptography lib).
- Agent TOFU trust anchor (/etc/rp/server_pubkey.pem).
- Local-approval enforcement (defense-in-depth): /etc/rp/ flag files for
  exec/restart/write/read with TTL (24h default), default-deny for unknown
  command types. Mitigates server compromise (review C3 in ADR).
- Telegram approval flow via n8n webhook for destructive ops in sensitive
  groups (prod/iarq).

#### F5 — Multi-User + Web Dashboard
- PocketID OIDC integration (forward_auth via Caddy).
- Users table with role (admin/operator/viewer) + accessible_groups[].
- Multi-user filtering middleware (admin sees all; non-admin filtered by
  accessible_groups).
- HTMX web dashboard with uPlot sparklines (Pico.css minimal styling).
- Prometheus /metrics endpoint with 14 metric families.
- Grafana dashboard JSON provisioned (17 panels).
- Magic-link enrollment flow with QR codes (F7-6).

#### F6 — Remote Control
- `rp ssh <host>`: Tailscale SSH preferred, classic SSH fallback.
- `rp screen <host>`: RustDesk Direct IP (default), Sunshine (Windows GPU),
  VNC (Linux fallback).
- `rp exec <host|@group>`: audited via signed commands API.
- `rp install-screen` for installing RustDesk/Sunshine/VNC clients.

#### F7 — Distribution
- GitHub Actions multi-OS PyInstaller release matrix (Linux x64/arm64,
  macOS x64/arm64, Windows x64).
- winget-pkgs manifest (Monxas.RemotePulse).
- install.ps1 PowerShell with self-elevation + Tailscale MSI install +
  NSSM service registration.
- Caddy public routing: rp.monxas.casa (install + enrollment public) +
  dash.rp.monxas.casa (OIDC-gated web dashboard).
- MkDocs Material public docs site (25 pages).
- Magic-link enrollment for non-technical users.

#### F8 — Hardening
- Tailscale ACL policy.hujson with 5 tags + 3 groups + 8 validation tests
  (lateral movement blocked, SSH check policy).
- pg_dump daily backup (systemd timer 03:00) + NAS sync + 30d retention.
- DR drill procedure (quarterly cadence, RTO 10min target).
- API compatibility handshake (Sec-RP-* headers, 426 enforcement,
  N-2 deprecation, semver tracking via agent_versions table).
- Canary deploy + N-1 binary auto-rollback (90s self-check timeout,
  signed upgrade commands).
- Security review: trufflehog (verified-only), semgrep, bandit, safety,
  cosign keyless OIDC signing of release artifacts.
- Dependabot weekly dep updates.

### Stats

- 30+ git commits, ~10,000+ lines added across 3 repos.
- 200+ tests across server + agent.
- 36+ server endpoints.
- 8 implementation phases F1-F8 completed end-to-end.

### Known Limitations

- Windows binary unsigned (SmartScreen warnings expected pre v2.0 with EV cert).
- Sunshine pairing remains one-time manual (PIN exchange limitation).
- PocketID OIDC client config required manually (not yet Ansible-provisioned).
- Telegram bot setup required manually (PRE-4).
- Tailscale ACL apply requires admin web UI or API key (PRE-3).

### Acknowledgements

- Built via parallel sub-agent orchestration with Claude Opus 4.7 (1M ctx).
- Devil's advocate critical review applied in-place to ADR-0008 (13 design
  changes including: eliminated tsnet sidecar Go in favor of tailscaled+serve,
  deferred RustDesk hbbs/hbbr server, added agent-side local-approval as
  defense-in-depth against server compromise, recalibrated 33d/9-10wk realistic
  effort vs 29d/6-8wk initial estimate).

## [Unreleased]

### Planned

- v1.1: GUI installer (Tauri) for family Windows users
- v1.2: WebSocket multi-channel (currently REST polling)
- v1.3: NetBird control-plane optional (Tailscale vendor escape)
- v2.0: EV code signing, MSI installer, code-reviewed pentest

## Versioning

See the [API compatibility policy](architecture/api-compat.md). In short:

- Agent and server both SemVer.
- N-2 deprecation window once v1.0.0 ships.
- REST routes prefixed by major version (`/v1/`, `/v2/`, ...).
