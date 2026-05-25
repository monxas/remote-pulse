# API compatibility policy

Remote-Pulse follows a **N-2 deprecation** policy and per-route SemVer.
The goal: agents in the field can run two minor versions behind the server
without breaking, and one major version behind in degraded mode.

This page documents the rules. The behaviour is also enforced
programmatically via the version-handshake protocol described below.

## Versioning scheme

- **Agent (`rp`):** strict SemVer `MAJOR.MINOR.PATCH`. Public releases on
  GitHub Releases with SHA256SUMS and (post-v0.8) cosign signatures.
- **Server (`rp-server`):** also SemVer, but with rolling release inside a
  major. Patch and minor bumps must be backward-compatible with N-2 agents.
- **REST API:** route-prefixed by major version. Today everything is under
  `/v1/`. A future breaking change becomes `/v2/`, with `/v1/` kept alive
  for the deprecation window.

## Deprecation window

| Channel | Supported actively | Logs warning | Rejected |
|---------|--------------------|--------------|----------|
| Agent vs server | v(N) to v(N-2) | v(N-3) | v(N-4) and older |
| Server vs agent | v(N) to v(N-2) | v(N-3) | v(N-4) and older |
| REST major (`/v1/`, `/v2/`, …) | current + previous | n/a | older than previous |

In practice, once v1.0.0 ships, v0.X is the "previous major" until v2.0.0;
then v1.X is supported through the v2.X line.

## Version-handshake protocol

On the first WebSocket connect, the agent sends:

```http
Sec-RP-Agent-Version: 0.5.2
Sec-RP-Min-Server: 0.5.0
```

The server replies with:

```http
Sec-RP-Server-Version: 0.7.1
Sec-RP-Min-Agent: 0.4.0
```

The agent applies the intersection rule:

| Outcome | Action |
|---------|--------|
| Agent and server both inside the supported window | Connect, proceed normally. |
| Agent within window but using features the server doesn't advertise | Agent disables those features locally (graceful degradation). |
| Either side is one step outside the window | Log warning, continue. CLI emits a banner. |
| Either side is more than one step outside | Server closes the connection with `{"error":"version_skew","required":">=0.5.0"}`. CLI surfaces this as a clear upgrade prompt. |

## Feature flags

`GET /v1/server/info` returns a capabilities array, e.g.:

```json
{
  "version": "0.7.1",
  "api": "v1",
  "capabilities": [
    "heartbeat.v1",
    "metrics.sparkline.v1",
    "keys.lifecycle.v1",
    "exec.local_approval.v1",
    "exec.telegram_approval.v1"
  ]
}
```

Agents:

- Unknown capability advertised by server → log warn, do not crash.
- Server requests a feature the agent does not implement → agent ACKs the
  command with `rejected_reason=unsupported_feature`. The command is logged
  as `rejected` in `commands`, no half-execution.

## Schema migrations

Server-side Postgres schema migrations use **Alembic** (SQLAlchemy-style).
Rules:

- Every migration must have a `downgrade()` that is **tested** in CI.
- Migrations that touch hypertables (`heartbeats`, `metric_samples`)
  preserve the partition layout.
- Major version bumps that include irreversible schema changes are
  documented in the changelog with explicit upgrade notes.

## Update + rollback

- **Default deploy mode:** canary 1 host → observe 10 minutes → propagate
  to the rest of the group.
- **Canary selection:** server picks the host with the lowest criticality
  score (group rank: `prod` > `family` > `default`). Override with
  `--canary-host=<name>`.
- **Post-upgrade health check:** the canary must emit a `version_handshake`
  with the new version and `self_check.ok=true` within 90 s.
- **Automatic rollback:** the agent keeps the N-1 binary at
  `/opt/rp/bin/rp-prev`. If the health check fails, the agent re-execs into
  the previous binary and reports a `rollback` event.
- **Major-version jumps** (`vX.* → v(X+1).*`) require `--force-major` plus a
  Telegram approval. The schema may not be reversible.

## Manual rollback

```bash
rp admin rollback <host>
```

Reads `agent_versions` table for the host, looks up the previous version,
issues a downgrade command. Same canary semantics apply.

## See also

- [Disaster recovery](../ops/disaster-recovery.md) — DR runbook covers
  fleet re-auth and key rotation, both of which are version-sensitive.
- [ADR-0008 Appendix G](https://docs.monxas.casa/architecture/adr/ADR-0008-remote-pulse/)
  — original compat / queue / update spec.
