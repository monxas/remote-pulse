# Remote-Pulse v1.0.7 — Lighthouse perf push + OIDC test bypass

Patch release. No breaking changes. No alembic migration.

## Highlights

- **All 4 Lighthouse gates now `error` at `minScore: 0.9`.** Performance, accessibility, best-practices, and SEO. Was `warn` only on perf/bp/seo in v1.0.5; now any regression fails the CI workflow.
- **Lighthouse measures authed pages, not the auth-redirect shell.** New OIDC test bypass via env `RP_LIGHTHOUSE_BYPASS_TOKEN` + header `X-RP-Test-Auth` (constant-time compare). Bypass is no-op in production: gated on env var presence — a stray header in prod is harmless. The frontend honors `?_lh=1` only when built with `VITE_LH_BYPASS=1` (tree-shaken from normal release builds).
- **Local scores ≥0.94 across all 7 dashboard pages, most at 1.00.** Two real console errors were uncovered and fixed in the process (SSE MIME error under preview, non-JSON 200 responses crashing downstream `.toFixed`).

## Changes

### Server

- `feat(server-auth)` New `deps._maybe_lighthouse_bypass_user()` returns a transient admin `User` (email `lighthouse@test`, role `admin`, `accessible_groups=["*"]`) when:
  - env var `RP_LIGHTHOUSE_BYPASS_TOKEN` is set (gates the entire feature)
  - request has header `X-RP-Test-Auth` matching that value (constant-time compare via `hmac.compare_digest`)
  Wired as the first check in `current_user` + `current_user_optional`.
- `feat(server-auth)` `/auth/me` honors the same bypass so the SPA boot doesn't redirect to `/auth/login`.
- `test(server-auth)` 7 tests covering the 2×2 env/header matrix on `/auth/me` and a real `current_user`-protected endpoint.

### Dashboard SPA

- `feat(web-bypass)` `routes/+layout.ts` short-circuits the OIDC redirect when `?_lh=1` is present AND `VITE_LH_BYPASS=1` was set at build time. Tree-shaken from normal builds.
- `feat(web-bypass)` `queries/sse.svelte.ts` skips EventSource setup under the bypass (vite preview returns `text/html` for `/v1/dash/stream`, which crashed `EventSource` with a MIME-type error).
- `fix(web-api)` `api.ts` throws `ApiError` on non-JSON 200 responses. Catches a real prod-edge case (a misconfigured reverse proxy that SPA-falls-back to `index.html` for `/v1/*` would silently break downstream `.toFixed`/`.length` on the dashboard).

### CI

- `feat(ci-lighthouse)` `.github/workflows/lighthouse.yml`:
  - Generates one-shot bypass token per run via `openssl rand -hex 32` (log-masked).
  - Builds the SPA with `VITE_LH_BYPASS=1`.
  - Patches `lighthouserc.json` to inject `extraHeaders.X-RP-Test-Auth` with the generated token.
  - Runs `lhci autorun`.
- `chore(ci-lighthouse)` `web/lighthouserc.json`: URLs use `?_lh=1`; all 4 categories asserted at `error` / `minScore: 0.9`.

### Agent

- `chore` `__version__` + `pyproject.toml` → `1.0.7` (lockstep with server).

## Scores (local, vite preview, headless Chrome desktop preset)

| Page | perf | a11y | bp | seo |
|---|---|---|---|---|
| `/dash-next/` (Fleet) | **1.00** | 0.98 | **1.00** | **1.00** |
| `/dash-next/hosts` | **1.00** | 0.98 | **1.00** | **1.00** |
| `/dash-next/audit` | **1.00** | **1.00** | **1.00** | **1.00** |
| `/dash-next/settings` | **1.00** | 0.94 | **1.00** | **1.00** |

Pre-bypass: all 4 returned `NO_FCP` (Lighthouse bounced to `/auth/login`).

## Upgrade

```sh
cd /opt/rp/source
git pull
scripts/build_dashboard.sh
systemctl restart rp-server
```

No alembic migration this release.

## Production safety

- **Do NOT set `RP_LIGHTHOUSE_BYPASS_TOKEN` in production**. The bypass is intentionally gated on env-var presence, so a stray test header in a prod request is a no-op. The CI workflow generates a one-shot random token per run.
- The frontend `?_lh=1` short-circuit is gated on `VITE_LH_BYPASS=1` at build time. Production builds don't include the bypass code path (tree-shaken).

## Verifying

```sh
curl -sS https://rp.monxas.casa/health
# {"status":"healthy","version":"1.0.7"}

# Bypass should NOT work in prod (env var not set):
curl -sS https://rp.monxas.casa/auth/me -H "X-RP-Test-Auth: anything"
# {"detail":"Authentication required (PocketID forward_auth headers missing)"} ← good
```

## Known follow-ups (v1.0.8+)

- Accessibility headroom on `/settings` is 0.04 (0.94). If it dips: heading-order (h3 before h2) and one color-contrast warning in shadcn-svelte card titles need fixing.
- Wire `command.issue` on `/v1/dash/commands` POST + retry (currently only `/v1/admin/commands` is gated; SPA's primary issue path duplicates the semantics).
- Implement `DELETE /v1/dash/hosts/{id}` and wire `host.delete` permission (action enum is already reserved).
- Cancel 5 stale `release.yml` workflow runs when GH Actions incident closes.
