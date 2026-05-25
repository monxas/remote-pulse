# Changelog

All notable changes to Remote-Pulse will be documented here. Format
follows [Keep a Changelog](https://keepachangelog.com).

## [Unreleased]

### Added (in progress)

- **F1** — Agent + server foundation, JWT enrollment, heartbeat loop,
  `rp install`, `rp status`, `rp version`.
- **F2** — Tailscale identity middleware + ephemeral auth-key issuance.
- **F3** — TimescaleDB hypertables + sparkline endpoint + TUI dashboard
  (`rp dash`) with 3-pane layout and `textual-plotext` sparklines.
- **F4** — SSH key lifecycle schema (`ssh_keys`, `groups`) + agent
  `rp keys init|status|sync|rotate|configure-sshd` + local-approval
  enforcement (`rp local allow-exec|deny-exec|approve-write|whitelist-*|
  evaluate|status`).

### Planned

- **F4-2 / F4-3** — `rp keys` CLI surface + REST router for distribution.
- **F4-6** — Telegram approval flow via n8n for destructive commands.
- **F5** — Web dashboard (HTMX + uPlot) + Grafana fleet dashboard +
  multi-user OIDC (PocketID) + `rp admin invite` flow.
- **F6** — Tailscale SSH wrapper (`rp ssh`), RustDesk Direct IP
  (`rp screen`), Sunshine on GPU hosts.
- **F7** — One-liner public installers (Linux/macOS curl-pipe-sh +
  Windows winget) + this docs site published to `rp.monxas.casa/docs`.
- **F8** — Hardening pass, DR drill, API compat policy enforcement,
  cosign signatures, v1.0.0 GA release.

## Versioning

See the [API compatibility policy](architecture/api-compat.md). In short:

- Agent and server both SemVer.
- N-2 deprecation window once v1.0.0 ships.
- REST routes prefixed by major version (`/v1/`, `/v2/`, ...).
