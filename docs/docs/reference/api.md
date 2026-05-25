# REST API reference

The server exposes a versioned REST API under `/v1/`. All non-bootstrap
routes require Tailscale identity (delivered automatically when traffic
crosses `tailscale serve`).

This page is a hand-written summary of the F1 + F2 + F3 + F4 surface.
Endpoints planned for F4+ are flagged. Once the OpenAPI generation is in
place (F8), the full schema will be served at `/openapi.json`.

## Conventions

- **Base URL:** `https://rp-server.tailnet.ts.net/` (tailnet) or
  `https://rp.monxas.casa/` (public, bootstrap-only).
- **Auth headers (tailnet):** `Tailscale-User-Login` injected by
  `tailscale serve`; do not set manually.
- **Auth headers (bootstrap):** `Authorization: Bearer <enrollment-jwt>`.
- **Versioning:** all routes prefixed with `/v1/`. See
  [API compatibility](../architecture/api-compat.md).

## Enrollment

### `POST /v1/enroll` — bootstrap

Consumes an enrollment JWT and returns a Tailscale auth-key.

**Request:**

```json
{
  "token": "eyJhbGc...",
  "hostname": "my-laptop",
  "machine_fingerprint": "sha256:abc...",
  "group": "family"
}
```

**Response 201:**

```json
{
  "host_id": "550e8400-e29b-41d4-a716-446655440000",
  "tailscale_authkey": "tskey-...",
  "server_pubkey": "ssh-ed25519 AAAA...",
  "agent_config": {
    "heartbeat_interval_s": 30,
    "metrics_interval_s": 60
  }
}
```

**Errors:**

- `401` — token invalid, expired or consumed.
- `429` — rate-limit on `/v1/enroll` (Caddy: 10 req/min/IP).

### `POST /v1/agent/reauth` — bootstrap

Re-issue a session token without full re-enrollment, after a server
restore.

**Request:**

```json
{
  "host_id": "550e8400-...",
  "last_known_server_pubkey": "ssh-ed25519 AAAA...",
  "machine_fingerprint": "sha256:abc..."
}
```

**Response 200:** same shape as `/v1/enroll`.

## Heartbeat

### `POST /v1/heartbeat`

Agent reports liveness and a small metric snapshot.

**Request:**

```json
{
  "host_id": "550e8400-...",
  "agent_ts": "2026-05-25T12:30:00Z",
  "cpu_pct": 42.1,
  "mem_pct": 61.4,
  "load_1m": 0.83,
  "uptime_s": 1234567,
  "agent_version": "0.4.2"
}
```

**Response 200:**

```json
{ "received_at": "2026-05-25T12:30:00.142Z" }
```

## Hosts

### `GET /v1/hosts`

List all hosts the caller can see (subject to `accessible_groups`).

Query params: `group`, `os`, `up` (bool).

**Response 200:**

```json
[
  {
    "host_id": "550e8400-...",
    "hostname": "pmx-50",
    "os": "linux",
    "group": "prod",
    "up": true,
    "last_seen_at": "2026-05-25T12:29:55Z",
    "agent_version": "0.4.2"
  }
]
```

### `GET /v1/hosts/{host_id}`

Full detail for one host.

## Metrics

### `GET /v1/metrics/{host_id}/sparkline`

Series for sparklines.

Query params:

| Param | Default | Description |
|-------|---------|-------------|
| `window` | `5m` | `5m`, `1h`, `24h`, `7d`, `30d`. |
| `series` | `cpu,mem,disk,net_rx,net_tx,latency` | Comma-separated. |
| `agg` | auto | `raw` or `5min`. `auto` picks based on window. |

**Response 200:**

```json
{
  "host_id": "550e8400-...",
  "window": "5m",
  "samples": {
    "cpu_pct":  [{"ts":"2026-05-25T12:25Z","v":42.1}, ...],
    "mem_pct":  [...]
  }
}
```

### `GET /v1/metrics/{host_id}/series`

Returns the list of available metric names for the host (useful for
discovering custom metrics).

## SSH keys

### `POST /v1/keys`

Register an agent-generated public key.

**Request:**

```json
{
  "host_id": "550e8400-...",
  "user_name": "root",
  "pubkey": "ssh-ed25519 AAAA...",
  "fingerprint": "SHA256:W+7BK0...",
  "algorithm": "ed25519"
}
```

**Response 201:** the persisted record.

### `GET /v1/keys`

Query params: `group`, `host_id`, `revoked` (bool, default false).

### `DELETE /v1/keys/{fingerprint}`

Revoke a key. Soft-delete: marks `revoked_at`, never `DELETE`s.

Query params: `reason`.

### `POST /v1/keys/distribute/{group}`

Materialise an `authorized_keys` blob for a group. Idempotent.

### `GET /v1/keys/authorized/{host_id}`

Used by agents polling on the 5-minute timer.

**Response 200:**

```json
{
  "content": "ssh-ed25519 AAAA... rp-managed-root@...\n",
  "sha256": "abc..."
}
```

## Admin <span class="rp-badge wip">F5</span>

### `GET /v1/admin/groups`

List groups.

### `POST /v1/admin/groups`

Create a group.

### `PATCH /v1/admin/groups/{name}`

Update.

### `DELETE /v1/admin/groups/{name}`

Soft-delete (only if no member hosts).

## Commands (TODO F4+) <span class="rp-badge planned">F4</span>

Routes for the WebSocket-based command channel and the audit-log query
surface (`GET /v1/commands?host_id=...&since=...`) are still landing. They
will be added here once stable.

## WebSocket channels <span class="rp-badge planned">F4</span>

| Path | Direction | Cadence |
|------|-----------|---------|
| `wss://.../v1/agent/ws/control` | bidirectional | heartbeat 30 s, commands on demand |
| `wss://.../v1/agent/ws/metrics` | agent → server | 60 s |
| `wss://.../v1/agent/ws/inventory` | agent → server | 5 min or on-change |
| `wss://.../v1/agent/ws/logs` | agent → server | continuous (opt-in) |
| `wss://.../v1/dash/ws` | server → client | ~2 s push for TUI/Web |

## See also

- [API compatibility policy](../architecture/api-compat.md)
- [SSH key lifecycle](../guide/ssh-keys.md)
