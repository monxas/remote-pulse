# Runbook — expose `/v1/agent/commands/*` through Caddy

**Context:** Phase 2.5 closes the command exec loop. The agent pulls
approved commands and posts results via two new endpoints:

- `GET  /v1/agent/commands/pending`
- `POST /v1/agent/commands/{command_id}/result`

These are intentionally **unauthenticated at the HTTP layer** for Phase 2.5
— the tailnet ACLs are the outer auth boundary. They therefore need to
live behind Caddy's `@public_api` matcher, otherwise `forward_auth` will
gate them and the agent (which has no OIDC session) will see 302s.

> **Phase 4 follow-up:** once per-host bearer tokens are in place, these
> paths can move back under `forward_auth` (or stay public with bearer
> verification done in-app). See the module docstring in
> `server/src/rp_server/routers/agent_commands.py`.

## Change

Append `/v1/agent/commands/pending` and `/v1/agent/commands/*` to the
existing `@public_api` matcher on `rp.monxas.casa` (LXCs 270 and 271 —
the keepalived VIP pair).

### Before

```caddyfile
@public_api path /auth/* /v1/info /health /dash-next /dash-next/*
handle @public_api {
    reverse_proxy 192.168.0.196:8080
}
```

### After

```caddyfile
# Phase 2.5: /v1/agent/commands/* is the agent execution loop. The two
# endpoints (pending poll + result POST) are tailnet-only and require no
# Caddy forward_auth. Server-side host_id check is the inner sanity
# filter; Phase 4 will introduce per-host bearer verification.
@public_api path /auth/* /v1/info /health /dash-next /dash-next/* /v1/agent/commands/pending /v1/agent/commands/*
handle @public_api {
    reverse_proxy 192.168.0.196:8080
}
```

## Apply

The Caddyfile is rendered by Ansible (`homelab-infra`, role
`roles/caddy_lxc`). Edit
`roles/caddy_lxc/templates/rp.monxas.casa.j2`, commit, then re-run the
play.

If you're applying out-of-band for a hot-fix on each Caddy LXC (270 and
271), as root:

```sh
# Idempotent sed: only adds the two paths if they're not already present.
grep -q '/v1/agent/commands/pending' /etc/caddy/sites/rp.monxas.casa \
  || sed -i \
       's|@public_api path /auth/\* /v1/info /health /dash-next /dash-next/\*|& /v1/agent/commands/pending /v1/agent/commands/\*|' \
       /etc/caddy/sites/rp.monxas.casa

caddy validate --config /etc/caddy/Caddyfile
systemctl reload caddy
```

Validate from outside afterwards (substitute a real host_id you control):

```sh
HOST_ID=11111111-1111-1111-1111-111111111111  # change me
curl -sS "https://rp.monxas.casa/v1/agent/commands/pending?host_id=$HOST_ID"
# Expect either {"commands": []} or a 404 if the host_id doesn't exist —
# importantly NOT a Caddy 302 redirect to /auth/login.
```

## Rollback

Remove the two extra path tokens from the `@public_api` line and
`systemctl reload caddy`. Agents will start getting 302 redirects and the
command loop will stop draining — heartbeat keeps working.

## Related

- `server/src/rp_server/routers/agent_commands.py` — the two endpoints.
- `agent/src/rp/daemon.py` — `_command_loop` that calls them.
- ADR-0008 §13 — original Ed25519 signed-command design (the layer Phase
  4 will reinstate alongside per-host bearer auth).
