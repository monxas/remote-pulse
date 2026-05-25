# Configuration

The agent reads its configuration from a TOML file plus environment
variables. CLI flags override both.

## Locations

| OS | Config path |
|----|-------------|
| Linux | `/etc/rp/agent.toml` |
| macOS | `/etc/rp/agent.toml` |
| Windows | `%PROGRAMDATA%\rp\agent.toml` |

Per-user dashboard config:

| OS | Dashboard config |
|----|------------------|
| Linux / macOS | `~/.config/rp/dash.toml` |
| Windows | `%APPDATA%\rp\dash.toml` |

## `agent.toml`

```toml
# Server URL. Tailnet hostname is preferred; public URL is bootstrap-only.
server_url = "https://rp-server.tailnet.ts.net"

# Host identity (set at install, do not edit by hand).
host_id    = "550e8400-e29b-41d4-a716-446655440000"
hostname   = "my-laptop"
group      = "family"

[heartbeat]
interval_s = 30
timeout_s  = 10

[metrics]
interval_s = 60
# Disable specific metric families if needed.
disabled = []

[ws]
reconnect_backoff_initial_s = 1
reconnect_backoff_max_s     = 60
jitter_pct                  = 20

[queue]
path          = "/var/lib/rp/queue.db"
max_size_mb   = 100
max_age_hours = 24

[local_policy]
# Path to the directory containing flag files. Default per-OS.
flag_dir = "/etc/rp"

[logging]
level  = "info"        # debug | info | warning | error
format = "console"     # console | json
```

## Environment variables

| Variable | Purpose |
|----------|---------|
| `RP_SERVER_URL` | Override `server_url`. |
| `RP_TOKEN` | Enrollment JWT (consumed by `rp install`). |
| `RP_GROUP` | Default group during enrollment. |
| `RP_HOSTNAME` | Override the reported hostname. |
| `RP_CONFIG_PATH` | Override config file location. |
| `RP_LOG_LEVEL` | Override `[logging].level`. |

## `dash.toml`

```toml
[server]
url = "https://rp-server.tailnet.ts.net"

[display]
refresh_ms      = 2000
sparkline_width = 40
sparkline_height = 1
default_sort    = "last_seen"  # last_seen | name | cpu | mem | group

[keybindings]
quit = "q"
refresh = "r"
filter = "/"
```

## Server config (informational)

The private server reads `homelab-infra/services/remote-pulse-server/config/`:

- `server.toml` — DB URL, JWT secret, Tailscale API token, signing key
  paths.
- `groups.yml` — declarative groups (see [SSH key lifecycle](../guide/ssh-keys.md#groups)).
- `users.yml` — multi-user `accessible_groups` (post F5).

These files live in the private repo and are not part of the public agent
distribution.
