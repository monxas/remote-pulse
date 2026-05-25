# Remote-Pulse Agent

Universal connectivity, health monitoring, and remote control agent for homelab and external nodes.

## Installation

```bash
# Via pipx (recommended)
pipx install remote-pulse

# Via uv (development)
cd agent && uv sync
uv run rp --help
```

## Quick Start

```bash
# Install and register agent
rp install --token=<JWT> --server=https://rp.monxas.casa

# Check status
rp status

# Run heartbeat once
rp heartbeat --once

# Run as daemon (systemd will do this)
rp heartbeat --daemon
```

## Commands

### Agent Management
- `rp install` - Install and register agent with server
- `rp register` - Re-register with server
- `rp heartbeat` - Send heartbeat to server
- `rp status` - Show agent status
- `rp version` - Show agent version
- `rp uninstall` - Uninstall agent and cleanup
- `rp dash` - Launch interactive TUI dashboard
- `rp local` - Manage local policy enforcement (see Security section)

### Remote Shell & Screen
- `rp ssh <host>` - SSH to a host (Tailscale SSH preferred, classic fallback)
- `rp screen <host>` - Open remote screen (RustDesk/Sunshine/VNC)
- `rp exec <host|@group> -- <cmd>` - Execute command on host or group (audited)

## Configuration

Configuration is stored in `/etc/rp/config.toml`:

```toml
host_id = "uuid"
server_url = "https://rp.monxas.casa"
heartbeat_interval_s = 30
group = "prod"  # optional: prod/iarq/family/default
```

## Security: Local-approval enforcement

Remote-Pulse implements defense-in-depth security through **local-approval enforcement** at the agent level. Even with valid server authentication, agents consult local flags and whitelists before executing commands.

### Why local-approval?

Server compromise is a real risk. If an attacker gains control of the server, they could sign valid commands to all agents. Local-approval provides a second layer of defense: the attacker must also gain SSH access to individual hosts to modify `/etc/rp/` policy files.

This defense-in-depth approach means:
- Server breach alone cannot execute arbitrary commands on sensitive hosts
- Audit logs capture attempted policy violations
- Critical operations require explicit human approval (Telegram flow)

### Policy tiers

Hosts are grouped into policy tiers based on sensitivity:

- **Sensitive groups** (`prod`, `iarq`): Strict enforcement, most commands require local flags or approval
- **Non-sensitive groups** (`family`, `default`): Lenient, server authentication sufficient for most operations

### Managing local policy

Check current policy status:
```bash
rp local status
```

Enable remote shell execution (24h TTL by default):
```bash
sudo rp local allow-exec
sudo rp local allow-exec --ttl=12h  # custom TTL
```

Disable remote shell execution:
```bash
sudo rp local deny-exec
```

Enable remote file writes (use sparingly):
```bash
sudo rp local approve-write --ttl=5m
```

Whitelist services for restart:
```bash
sudo rp local whitelist add restart nginx
sudo rp local whitelist add restart 'docker-*'  # glob patterns supported
sudo rp local whitelist show restart
```

Whitelist paths for read access:
```bash
sudo rp local whitelist add read '/var/log/*.log'
sudo rp local whitelist add read '/etc/rp/*'
sudo rp local whitelist show read
```

Dry-run command evaluation (no execution):
```bash
rp local evaluate exec_shell --group=prod
rp local evaluate file_read --payload='{"path":"/var/log/syslog"}' --group=prod
```

### Command authorization matrix

| Command | Sensitive Groups (prod/iarq) | Non-sensitive (family/default) |
|---------|------------------------------|-------------------------------|
| `exec_shell` | Requires `/etc/rp/allow-remote-exec` flag (24h TTL) | Allowed |
| `pkg_install` | Requires Telegram approval | Allowed |
| `service_restart` | Only whitelisted services in `/etc/rp/restart-whitelist` | Allowed |
| `file_read` | Only paths matching `/etc/rp/read-allowlist` globs | Allowed |
| `file_write` | Requires `/etc/rp/allow-remote-write` flag; external paths need approval | Paths outside `/etc/rp/` or `/opt/rp/` need approval |
| `screen_open` | Always allowed (display-only) | Always allowed |
| `ssh_keys_sync` | SHA256 verification against stored reference | SHA256 verification |
| `agent_upgrade` | Major version changes require approval | Minor bumps allowed |
| `reboot` | Always requires Telegram approval (double-confirm) | Requires approval (single confirm) |

### Default-deny philosophy

Unknown command types are **always denied** regardless of group. This ensures that future command types cannot be exploited without explicit agent updates.

### Combined with server-side security

Local-approval works alongside server-side security:

1. **Server signature**: All commands are signed with Ed25519, verified by agent
2. **Local-approval**: Agent checks flags/whitelists before execution
3. **Telegram approval**: Destructive operations require human confirmation via Telegram bot
4. **Audit log**: All decisions logged to immutable Postgres table + Loki

This multi-layer approach ensures no single point of failure compromises fleet security.

## Remote Shell + Screen

Remote-Pulse provides unified remote access via SSH and screen sharing.

### SSH: `rp ssh <host>`

Smart SSH wrapper that prefers Tailscale SSH (when available) and falls back to classic SSH with managed keys.

**Examples:**
```bash
# Interactive shell (auto-detects Tailscale SSH)
rp ssh pmx-50

# Specific user
rp ssh carmelo --user=ramon

# Remote command
rp ssh lxc-280 -- systemctl status rp-server

# Force classic SSH (skip Tailscale)
rp ssh pmx-51 --force-classic

# Custom port
rp ssh external-host --port=2222
```

**How it works:**
1. Resolves hostname via server `/v1/hosts` API (Tailscale IP + capabilities)
2. Tries Tailscale SSH (`tailscale ssh user@host.ts.net`) if enabled on target
3. Falls back to classic SSH with managed key (`ssh -i /etc/rp/host_key`)
4. Passthrough stdin/stdout/stderr for full interactive shell support

### Screen Sharing: `rp screen <host>`

Launch local screen-sharing client (RustDesk/Sunshine/VNC) connecting to remote host via Tailscale Direct IP.

**Examples:**
```bash
# Auto-select best protocol (RustDesk > Sunshine > VNC)
rp screen pmx-50

# Force specific protocol
rp screen carmelo --protocol=rustdesk
rp screen ai-tagger --protocol=sunshine
rp screen lxc-100 --protocol=vnc

# Launch in background
rp screen pmx-51 --no-wait
```

**Supported protocols:**
- **RustDesk**: Direct IP P2P (no relay), password-based auth, cross-platform
- **Sunshine**: Low-latency game streaming (Moonlight client), Windows GPU hosts
- **VNC**: Linux fallback (TigerVNC/Remmina)

**Requirements:**
- **Target host**: Must have RustDesk/Sunshine/VNC installed + capability reported
- **Local machine**: Must have corresponding client (RustDesk/Moonlight/VNC viewer)

**Installation:**
```bash
# macOS
brew install --cask rustdesk

# Linux (Debian/Ubuntu)
sudo apt install rustdesk

# Windows
winget install RustDesk.RustDesk
```

### Remote Exec: `rp exec <host|@group> -- <cmd>`

Execute audited commands on remote hosts or groups. Commands are signed by server (F4-4) and logged to immutable audit trail.

**Examples:**
```bash
# Single host
rp exec pmx-50 -- systemctl status caddy

# Group (sequential by default)
rp exec @homelab -- uptime

# Group (parallel)
rp exec @family -- df -h --parallel

# With timeout
rp exec @prod -- apt update --timeout=120
```

**Security:**
- Commands go through `/v1/admin/commands` endpoint (server-side signing)
- Sensitive groups (`@prod`, `@iarq`) require Telegram approval (F4-6)
- All executions logged to audit trail (Postgres + Loki)
- Requires F4-4 (signed commands) and F4-6 (approval) deployed on server

**Note:** `rp exec` requires server support. If F4-4/F4-6 not deployed, you'll see an error message.

## License

Apache-2.0
