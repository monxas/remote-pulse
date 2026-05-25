# Runbook — expose `/dash-next/` through Caddy

**Context:** ADR-0009 Phase 0 ships the new SvelteKit SPA mounted by FastAPI
at `/dash-next/`. Caddy on LXC 270/271 currently exposes `/auth/*` via a
`@public_api` matcher so the OIDC dance loads unauthenticated. We need to
extend that matcher to cover the SPA shell, otherwise Caddy's
`forward_auth` will gate the very assets the SPA needs to bootstrap the
login flow.

## Change

Update the `@public_api` matcher on `rp.monxas.casa` (LXCs 270 and 271 — the
keepalived VIP pair) to include `/dash-next` and `/dash-next/*`.

### Before

```caddyfile
rp.monxas.casa {
    # ...

    @public_api path /auth/* /v1/info /health
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

    # ADR-0009: /dash-next and /dash-next/* are part of the public matcher
    # because the SPA shell itself enforces auth (it fetches /auth/me and
    # redirects to /auth/login on 401). Adding it here lets the shell load
    # without going through forward_auth, which would 302 before the SPA
    # ever boots.
    @public_api path /auth/* /v1/info /health /dash-next /dash-next/*
    handle @public_api {
        reverse_proxy 192.168.0.196:8080
    }

    # ...
}
```

## Apply

The Caddyfile is rendered by Ansible (`homelab-infra`, role
`roles/caddy_lxc`). Edit `roles/caddy_lxc/templates/rp.monxas.casa.j2`,
commit, then re-run the play. If you're applying out-of-band for a
hot-fix:

```sh
# On each Caddy LXC (270 and 271), as root:
sudoedit /etc/caddy/sites/rp.monxas.casa
caddy validate --config /etc/caddy/Caddyfile
systemctl reload caddy
```

Validate from outside afterwards:

```sh
curl -sSI https://rp.monxas.casa/dash-next/  | head -5
# Expect: HTTP/2 200, content-type: text/html; charset=utf-8
```

## Rollback

Revert the matcher line and `systemctl reload caddy`. The v1.0 `/dash/`
dashboard is unaffected.

## Related

- ADR-0009 §3.8 (build & deploy) and §7 Phase 0 (foundations).
- `server/src/rp_server/main.py` — `app.mount("/dash-next", …)`.
- `scripts/build_dashboard.sh` — builds + stages the SPA into the FastAPI
  package.
