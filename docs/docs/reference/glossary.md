# Glossary

| Term | Definition |
|------|------------|
| **Agent** | The `rp` process running on each managed host. Sends heartbeats, executes audited commands, enforces local-approval. |
| **CLI** | Same `rp` binary, used from a workstation for `rp dash`, `rp ssh`, `rp keys`, etc. |
| **Audit log** | Append-only `commands` table in Postgres. Mirrored to Loki. |
| **Bootstrap** | The brief window during enrollment when an agent is not yet on the tailnet and uses the public HTTPS endpoint. |
| **Canary deploy** | Upgrade strategy: roll to one low-criticality host first, observe 10 min, then propagate. |
| **CGNAT** | Carrier-Grade NAT. Tailscale tunnels through it transparently. |
| **Cosign** | Sigstore tool for signing binaries; planned for F8 releases. |
| **DERP** | Tailscale's Designated Encrypted Relay for Packets. Fallback when direct WireGuard fails. |
| **Enrollment JWT** | One-shot HS512-signed token used by the agent on first install. TTL 24 h, bound to host fingerprint. |
| **Ephemeral auth-key** | Tailscale auth-key issued via API with `ephemeral=true, reusable=false`. |
| **Fleet** | All hosts managed by a single Remote-Pulse server. |
| **Group** | Logical grouping of hosts (`prod`, `family`, `iarq`, ...). Drives ACLs and `authorized_keys`. |
| **Heartbeat** | 30-second liveness ping from agent to server. |
| **Hypertable** | TimescaleDB construct for time-series partitioning. |
| **Local-approval** | Agent-side flag-file gating that defends against server compromise. |
| **MagicDNS** | Tailscale-internal DNS that maps tailnet device names to IPs. |
| **N-2 deprecation** | Compatibility window: server supports agents v(N) and v(N-1) and v(N-2). |
| **PBS** | Proxmox Backup Server. Used for LXC 280 snapshots. |
| **PocketID** | Self-hosted OIDC provider. Backs the web dashboard auth. |
| **Promtail** | Loki agent for log shipping. Bundled opt-in via `--with-logs`. |
| **PyInstaller** | Python-to-single-binary packager. Used for non-Python OS distributions. |
| **`rp local`** | CLI subcommand for managing local-approval flags. |
| **`tailscale serve`** | Tailscale reverse proxy that injects identity headers. |
| **Tailnet** | The private WireGuard network managed by a Tailscale account (here: `monxas`). |
| **TimescaleDB** | Postgres extension for time-series workloads. |
| **TOFU** | Trust-on-first-use. The agent pins the server pubkey at enrollment. |
| **TTL** | Time-to-live. Applies to enrollment tokens, approval acks, local-approval flags. |
| **WS** | WebSocket. Multi-channel data plane between agent and server. |
