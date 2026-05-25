# TUI dashboard

`rp dash` is the primary interface for power-users. It is a Textual
application that renders inline sparklines via `textual-plotext` and
subscribes to a WebSocket for ~2 s push updates.

## Launch

```bash
rp dash
```

Connect to a non-default server:

```bash
rp dash --server=https://rp.monxas.casa
```

## Layout

```text
┌────────────────────────────────────────────────────────────────────┐
│ Remote-Pulse  · 12 hosts up · 1 down · last refresh 2s ago         │
├──────────────────┬─────────────────────────────────┬───────────────┤
│ HostList         │ HostDetail                      │ Logs / Exec   │
│                  │                                 │               │
│ ● pmx-50    prod │ pmx-50  (linux x86_64)          │ 12:30:01 hb   │
│ ● pmx-51    prod │   group=prod                    │ 12:30:31 hb   │
│ ● vm-208    prod │   ts=100.86.42.7                │ 12:30:33 ssh  │
│ ● carmelo  fam.  │                                 │   key sync ok │
│ ○ iarq-rag iarq  │  cpu  ▁▂▂▃▅▆▆▇▆▅▃▂▁    42%      │               │
│ ● pi-hole  prod  │  mem  ▃▃▃▄▄▄▅▅▅▄▄▃▃   61%      │               │
│ ...              │  disk ▁▁▁▁▁▁▁▁▂▂▂▂▂   34%      │               │
│                  │  net⬆ ▂▃▅▆▆▅▃▂▂▁▁▁▁   12 KB/s  │               │
│                  │  net⬇ ▃▄▆▇▇▆▄▃▂▂▁▁▁  120 KB/s  │               │
│                  │  rtt  ▁▁▂▂▁▁▁▁▁▁▁▁▁   8 ms     │               │
└──────────────────┴─────────────────────────────────┴───────────────┘
```

The 3-pane layout:

- **Left — HostList.** All known hosts with status dot (●/○), name and group.
  Sorted by `last_seen` descending.
- **Centre — HostDetail.** Static metadata for the selected host plus six
  sparkline rows: CPU %, memory %, disk %, net TX bps, net RX bps, RTT to
  server.
- **Right — Logs / Exec.** Tail of structured events for the selected host
  (heartbeats, key syncs, command outputs).

## Sparklines

Each sparkline is **5 minutes of data at the native sample frequency**:

| Series | Frequency | Source |
|--------|-----------|--------|
| `cpu_pct` | 60 s | `psutil.cpu_percent` aggregated |
| `mem_pct` | 60 s | `psutil.virtual_memory` |
| `disk_used_pct` | 60 s | `/` filesystem |
| `net_tx_bps` | 60 s | delta of `psutil.net_io_counters().bytes_sent` |
| `net_rx_bps` | 60 s | delta of `psutil.net_io_counters().bytes_recv` |
| `latency_ms` | 30 s | `received_at - agent_ts` from heartbeat |

Backed by TimescaleDB continuous aggregates so even multi-month windows are
fast (see [storage details](../architecture/components.md#storage)).

## Refresh cadence

- **WebSocket push:** every ~2 s the server fans out deltas on
  `wss://rp-server.tailnet/v1/dash/ws`.
- **Manual refresh:** press `r` to force a full re-query (also resets the
  sparkline buffers from the server's continuous aggregates).
- **Reconnect:** exponential backoff 1 s → 60 s with ±20 % jitter if the WS
  drops. A footer banner shows the disconnect state.

## Keybindings

| Key | Action |
|-----|--------|
| `↑` / `↓` | Move host selection |
| `Enter` | Pin detail pane on the selected host |
| `Tab` / `Shift+Tab` | Cycle focus across panes |
| `r` | Force refresh |
| `/` | Filter hosts by substring |
| `g` | Group-by toggle (none / group / OS) |
| `s` | Sort toggle (`last_seen` / `name` / `cpu` / `mem`) |
| `?` | Help overlay |
| `q` or `Ctrl+C` | Quit |

## Status colours

| Colour | Meaning |
|--------|---------|
| Green (`●`) | Heartbeat within last 60 s. |
| Yellow (`●`) | Heartbeat between 60–180 s. |
| Red (`○`) | No heartbeat for >180 s. Telegram alert fires at this threshold. |
| Grey (`○`) | Host registered but never seen heartbeat. |

## Server connection

By default `rp dash` reads `~/.config/rp/dash.toml`:

```toml
[server]
url = "https://rp.monxas.casa"
# auth is automatic via Tailscale identity headers
ws_path = "/v1/dash/ws"
reconnect_max_s = 60
```

If the workstation is not on the tailnet, `rp dash` falls back to the public
HTTPS endpoint and uses OIDC (PocketID) login. The dashboard scopes hosts
by the user's `accessible_groups`.

## Set up screen sharing

Each host in the TUI shows screen-sharing capabilities (RustDesk / Sunshine /
TigerVNC) when they have been provisioned on that host. To enable them, run
the matching `rp install-screen` command **on the host you want to control**:

```bash
# Linux / macOS / Windows — generic, P2P over Direct IP
sudo rp install-screen rustdesk

# Windows GPU hosts — low-latency Moonlight streaming
rp install-screen sunshine

# Linux GUI hosts without GPU — TigerVNC fallback
sudo rp install-screen vnc

# Check what is currently installed
rp install-screen status
```

The agent generates the secret, binds to the Tailscale interface, and POSTs
the resulting capabilities to the server. After that, from your workstation:

```bash
rp screen <host>
```

picks the best protocol automatically (RustDesk > Sunshine > VNC). See the
[CLI reference](cli.md) for the full flag list.

## See also

- [Web dashboard](web-dashboard.md) — same data, browser-based.
- [`rp` CLI reference](cli.md) — full CLI surface.
- [Components — storage](../architecture/components.md) — what backs the
  sparklines.
