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

- `rp install` - Install and register agent with server
- `rp register` - Re-register with server
- `rp heartbeat` - Send heartbeat to server
- `rp status` - Show agent status
- `rp version` - Show agent version
- `rp uninstall` - Uninstall agent and cleanup
- `rp dash` - Launch interactive TUI dashboard
- `rp local` - Manage local policy enforcement (see Security section)

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

## License

Apache-2.0
