# Web dashboard <span class="rp-badge planned">F5</span>

The web dashboard is the **primary surface for non-power-users**: family,
clients, and anyone reading the fleet from a phone. It is a thin FastAPI +
HTMX layer over the same data plane as the TUI.

## Access

- **Public URL:** `https://dash.rp.monxas.casa`
- **Tailnet URL:** `https://rp-server.tailnet.ts.net/dash`

Both routes are auth-gated:

- **Public** — Caddy `forward_auth` → PocketID OIDC (passkey login).
- **Tailnet** — Tailscale identity header (`Tailscale-User-Login`),
  zero-click for users on the tailnet.

## Multi-user scoping

Each PocketID user has a role (`admin`, `operator`, `viewer`) and a list of
`accessible_groups`. The dashboard filters hosts accordingly:

| Role | Sees | Can do |
|------|------|--------|
| `admin` | All groups | Exec, restart, reboot, key revoke, invite users |
| `operator` | Allowed groups | Exec, restart |
| `viewer` | Allowed groups | Read-only sparklines + audit log |

Family users logged in see only `family` hosts; iarquitectos clients see
only `iarq`. No cross-group leak.

## Layout

A responsive single-page table, one row per host, with inline uPlot
sparklines at 30 px height. Click a row to expand a detail drawer with
the same six series as the TUI, plus the audit-log tail.

## Status

!!! info "Coming in F5"
    The web dashboard ships in F5. Source lives under
    [`server/src/rp_server/web/`](https://github.com/monxas/remote-pulse/tree/main/server/src/rp_server)
    once that phase starts.

## See also

- [Security model](../architecture/security.md)
- [TUI dashboard](tui-dashboard.md) — primary surface for power-users
