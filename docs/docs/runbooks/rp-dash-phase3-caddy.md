# Runbook — extend Caddy `@public_api` matcher for `/dash/*` (ADR-0009 Phase 3 cutover)

**Context:** ADR-0009 Phase 3 retires the Jinja+HTMX dashboard at `/dash/*`
and replaces it with a server-side 302 redirect to the SvelteKit SPA at
`/dash-next/*` (see `rp_server.routers.dash_redirect`). The one
preserved endpoint — `/dash/host/{id}/sparkline-data` — is already in
the matcher.

For the redirects to reach the backend, Caddy must proxy `/dash` and
`/dash/*` to FastAPI *without* going through `forward_auth`. The
redirect handler itself is auth-free (it just emits a 302), and the
SPA at the redirect target enforces auth on its own.

## Change

Update the `@public_api` matcher on `rp.monxas.casa` (LXCs 270 and 271 —
the keepalived VIP pair) to include `/dash` and `/dash/*`.

### Before (Phase 2.5 — post `rp-agent-commands-caddy.md`)

```caddyfile
rp.monxas.casa {
    # ...

    @public_api path /auth/* /v1/info /health /dash-next /dash-next/* /v1/agent/commands/pending /v1/agent/commands/* /dash/host/*/sparkline-data
    handle @public_api {
        reverse_proxy 192.168.0.196:8080
    }

    # ...
}
```

### After

```caddyfile
rp.monxas.casa {
    # ...

    # ADR-0009 Phase 3: /dash and /dash/* are now backend redirects that
    # bounce to /dash-next/. They MUST bypass forward_auth so the redirect
    # itself is served (forward_auth would 302 the request to /auth/login
    # before FastAPI ever sees it, defeating the cutover). Auth is
    # enforced by the SPA at the redirect target.
    @public_api path /auth/* /v1/info /health /dash-next /dash-next/* /v1/agent/commands/pending /v1/agent/commands/* /dash /dash/*
    handle @public_api {
        reverse_proxy 192.168.0.196:8080
    }

    # ...
}
```

Note: `/dash/*` already implicitly covers `/dash/host/*/sparkline-data`,
so the explicit token from the previous runbook can be dropped (kept
above for the diff clarity — feel free to remove it when applying).

## Apply

The Caddyfile is rendered by Ansible (`homelab-infra`, role
`roles/caddy_lxc`). Edit `roles/caddy_lxc/templates/rp.monxas.casa.j2`,
commit, then re-run the play. For a hot-fix:

```sh
# On each Caddy LXC (270 and 271), as root:
sudoedit /etc/caddy/sites/rp.monxas.casa
caddy validate --config /etc/caddy/Caddyfile
systemctl reload caddy
```

Validate from outside:

```sh
curl -sSI https://rp.monxas.casa/dash/         | head -5
# Expect: HTTP/2 302, location: /dash-next/

curl -sSI https://rp.monxas.casa/dash/hosts    | head -5
# Expect: HTTP/2 302, location: /dash-next/hosts
```

## Rollback

Revert the matcher line (drop `/dash /dash/*`) and `systemctl reload
caddy`. Inside the server, revert the `dash_redirect` mount by reverting
the commit (the old `web.router` module is still on disk for one
release).

## Related

- ADR-0009 §7 Phase 3 (cutover).
- `server/src/rp_server/routers/dash_redirect.py` — redirect logic +
  preserved sparkline endpoint.
- `server/src/rp_server/main.py` — router include site.
- `docs/docs/runbooks/rp-dash-next-caddy.md` — Phase 0 matcher addition.
- `docs/docs/runbooks/rp-agent-commands-caddy.md` — Phase 2.5 matcher.
