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

## Configuration

Configuration is stored in `/etc/rp/config.toml`:

```toml
host_id = "uuid"
server_url = "https://rp.monxas.casa"
heartbeat_interval_s = 30
```

## License

Apache-2.0
