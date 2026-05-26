# Remote-Pulse v1.0.4 — Phase 4 finish + Phase 5 CI gate

Patch release. No breaking changes. Operator action required for the new alembic migration (`alembic upgrade head`).

## Highlights

- **Settings mutations now audited end-to-end.** Every group/user create/update/delete from `/v1/dash/settings/*` writes a row into the new `audit_events` table atomically with the mutation commit. The rows surface in `/v1/dash/audit` (and the dashboard's Audit page) alongside the synthetic timeline. User updates capture a structured `{before, after}` diff. No-op updates skip the write.
- **Magic-link issuance from the dashboard.** Admins can now mint enrollment tokens from the `/enroll` page (was CLI/Telegram only). Group dropdown stays in sync with `/settings/groups`. Active links can be revoked from a table below the form. Soft-revoke (no DB migration) — agent-side consume path already checks `expires_at` and `used_count >= max_uses`.
- **Phase 5 CI quality gate established.** `@axe-core/playwright` on 7 dashboard pages (WCAG 2.0/2.1 A+AA, baseline mode) plus `@lhci/cli` Lighthouse CI on 4 pages (warn-only, target ≥0.9 perf/a11y/best-practices). Two new workflows under `.github/workflows/`. ADR-0009 Phase 5 progress section.

## Changes

### Server

- `feat(server-audit)` New alembic `008_audit_events.py` adds `audit_events(id, ts, actor, action, resource_type, resource_id, payload jsonb)` with indexes on `ts DESC`, `actor`, `(resource_type, resource_id)`, `action`.
- `feat(server-audit)` `AuditEvent` SQLAlchemy model.
- `feat(server-audit)` `dash_settings.py` emits 5 action types (`settings.group.{create,delete}`, `settings.user.{create,update,delete}`) inside the same transaction as the mutation. `user.update` builds `{changes: {field: {before, after}}}` payload; no-ops don't emit.
- `feat(server-audit)` `dash_audit.py` merges `audit_events` rows with the existing synthetic timeline, enriches settings.* rows with their payload.
- `feat(dash-enroll)` New router `dash_enroll.py` with `POST/GET/DELETE /v1/dash/enroll/links` (admin-only). Reuses `auth.create_enrollment_token` — no logic duplication.
- `test(server)` +10 settings-audit tests, +13 enroll-links tests. All green.

### Dashboard SPA

- `feat(web-audit)` `api.ts`, `AuditEvent.svelte`, audit page rendering for the 5 new actions + `group` target type.
- `feat(web-enroll)` `/enroll` page replaces placeholder: form (group select from `/settings/groups`, ttl_hours, max_uses, label), result card with copy-to-clipboard URL + collapsible JWT, active-links table with revoke button.
- `feat(web-a11y)` `@axe-core/playwright@4.10.2` + `@lhci/cli@0.14.0` devDeps. `test:a11y` and `lighthouse` npm scripts. Baseline output excluded from git via `.gitignore` and `.prettierignore`.
- `test(web)` New `a11y.spec.ts` (7 pages, baseline mode). New `enroll.spec.ts` smoke. Vitest 45/45.

### CI

- `.github/workflows/a11y.yml` — runs `test:a11y` on PR, uploads baseline JSON artifact.
- `.github/workflows/lighthouse.yml` — builds + previews + `lhci autorun` on PR, uploads `.lighthouseci/` artifact.

### Agent

- `chore` `__version__` + `pyproject.toml` → `1.0.4` (lockstep with server).

## Upgrade

```sh
cd /opt/rp/source
git pull
# Alembic migration for audit_events table:
cd server
uv run alembic upgrade head
cd ..
scripts/build_dashboard.sh
systemctl restart rp-server
```

Verify migration applied:
```sh
sudo -u postgres psql -d remote_pulse -c "\d audit_events"
```

## Verifying

```sh
# Health
curl -sS https://rp.monxas.casa/health
# {"status":"healthy","version":"1.0.4"}

# Audit endpoint (admin session cookie required)
curl -sS https://rp.monxas.casa/v1/dash/audit?limit=10

# Magic-link from CLI (sanity that the new endpoint works):
# POST /v1/dash/enroll/links — see API docs
```

## Known baseline violations (Phase 5)

The axe-core baseline detected 2 issues on every page:
- **Critical: `button-name`** — at least one icon-only button is missing an accessible name (likely the theme/user menu trigger in `NavBar`).
- **Serious: `color-contrast`** — at least one element fails WCAG AA contrast against the Radix dark tokens.

These will be fixed in v1.0.5 — the baseline is recorded so the regression check can be flipped from warn-only to fail-on-regression.

## Known follow-ups (v1.0.5+)

- Fix the 2 baseline a11y violations and flip `checkA11y` to throw on regression.
- Promote Lighthouse assertions from warn to error once scores reach ≥0.9.
- OIDC-stub integration job so Lighthouse measures authed pages, not the redirect shell.
- Playwright E2E flows: login, issue/approve command, enroll host (ADR-0009 Phase 5).
- Cancel the 5 stale `release.yml` workflow runs from the 2026-05-25 GH Actions outage.
