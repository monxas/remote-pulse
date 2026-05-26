# Remote-Pulse v1.0.5 — row-level ACL + Phase 5 E2E + a11y gate

Patch release. No breaking changes. Operator action required for the new alembic migration (`alembic upgrade head` brings 008 → 009).

## Highlights

- **Row-level ACL per action.** New `user_permissions` table grants operators specific actions (`command.issue`, `command.approve`, `host.delete`, `enroll.create`) scoped to a group or `*`. Admins still pass everything. `POST /v1/admin/commands` is the first endpoint wired to enforce `command.issue` — operators without a matching grant get 403. Other admin endpoints keep their existing role gate with a TODO trail. A `Key` icon in Settings → Users opens a per-user Permissions dialog (admin only) to grant/revoke. Both grants and revokes write audit rows (`settings.permission.{grant,revoke}`).
- **Optimistic UI on Settings + Permissions.** All 5 Settings mutations + the 2 new Permissions mutations now use TanStack Query's `onMutate / onError / onSettled` pattern. Rows appear instantly, snap back on server error (with toast), and reconcile via `invalidateQueries` on settle. Patch helpers extracted as pure functions and unit-tested.
- **Phase 5 a11y gate flipped to fail-on-regression.** The two violation categories from the v1.0.4 baseline are fixed: `button-name` (root cause: `Button.svelte` was dropping `aria-label` on the `<button>` branch — only `<a>` spread `...rest`) and `color-contrast` (accent token ramp swapped to blue-12 in light, slate-1 contrast color in dark). axe-core spec now hard-asserts `expect(violations).toEqual([])`. Lighthouse a11y category flipped from `warn` to `error` with `minScore: 0.9`.
- **4 real E2E flows under Playwright.** `login-and-fleet`, `issue-command`, `approve-command`, `enroll-magic-link` — each mocks `/auth/me` + relevant `/v1/dash/*` endpoints and asserts golden-path UX (toast, optimistic insert, row removal, etc.). Plus `helpers/{auth,fixtures}.ts` factories. `playwright.config.ts` `baseURL` finally points at `/dash-next/` with the trailing slash that the URL constructor demands. 13/13 specs green (4 new + 2 smoke + 7 a11y).

## Changes

### Server

- `feat(server-permissions)` New alembic `009_user_permissions.py` — `user_permissions(id, user_id FK users(id) ON DELETE CASCADE, action, scope DEFAULT '*', granted_by, granted_at, UNIQUE(user_id, action, scope))` plus indexes on `(user_id)` and `(action)`.
- `feat(server-permissions)` `UserPermission` SQLAlchemy model.
- `feat(server-permissions)` New module `rp_server.permissions` with `ALLOWED_ACTIONS`, `is_action_allowed`, `user_has_permission(db, user, action, scope)`. Admin short-circuit, wildcard scope beats per-scope, inactive users always denied.
- `feat(server-permissions)` 3 admin-only endpoints under `/v1/dash/settings/users/{id}/permissions` — `GET` (also echoes `allowed_actions` enum so the UI doesn't ship its own copy), `POST` (201/409), `DELETE` (204/404). Both grant and revoke emit `settings.permission.grant` / `settings.permission.revoke` audit rows.
- `feat(server-commands)` `POST /v1/admin/commands` calls `user_has_permission(db, user, "command.issue", host.group_name)` before issuing.

### Dashboard SPA

- `feat(web-permissions)` `PermissionsDialog.svelte` — admin-only modal with grants table (action / scope / granted_by / granted_at / revoke) + grant form (`<select>` action + `<input>` scope with `<datalist>` of group names + `*`). Key icon button in Settings → Users opens it.
- `feat(web-settings)` 7 mutations refactored to optimistic. Pure patch helpers in `queries/index.ts` are unit-tested (`optimistic.test.ts`, 10 tests).
- `fix(web-a11y)` `Button.svelte` now binds `aria-label` and `title` on both `<a>` and `<button>` branches. Token swap in `tokens.css` (light: `--accent-text` blue-11→blue-12, `--accent-solid` blue-9→blue-11; dark: `--accent-contrast` white→slate-1). All ratios ≥AA.
- `chore(web-a11y)` axe-core spec switches from baseline mode to fail-on-regression. Lighthouse a11y assertion flipped warn → error.

### CI / E2E

- `feat(web-e2e)` 4 new flow specs + 2 helper modules. `playwright.config.ts` baseURL + healthcheck fixed.

### Agent

- `chore` `__version__` + `pyproject.toml` → `1.0.5` (lockstep with server).

## Upgrade

```sh
cd /opt/rp/source
git pull
# Alembic migration for user_permissions table:
cd server
set -a; source /etc/rp/server.env; set +a   # needs POSTGRES_URL + JWT_SECRET in env
sudo -u rp env POSTGRES_URL="$POSTGRES_URL" JWT_SECRET="$JWT_SECRET" \
    /opt/rp/source/server/.venv/bin/alembic upgrade head
cd ..
scripts/build_dashboard.sh
systemctl restart rp-server
```

Verify migration applied:
```sh
sudo -u postgres psql -d remote_pulse -c "\d user_permissions"
```

## Verifying

```sh
curl -sS https://rp.monxas.casa/health
# {"status":"healthy","version":"1.0.5"}

# Lighthouse a11y will now FAIL the workflow if any URL scores <0.9.
# axe-core will FAIL if any page reports a violation (was baseline-only).
```

## Known follow-ups (v1.0.6+)

- Wire `command.approve`, `host.delete`, `enroll.create` permission enforcement on their respective endpoints (currently only `command.issue` is gated; others keep role gate with TODO).
- Lighthouse perf + best-practices + seo assertions still `warn`-only. Flip to `error` once scores ≥0.9.
- OIDC stub for Lighthouse so it can measure authed pages instead of the auth-redirect shell.
- Cancel the 5 stale `release.yml` workflow runs from the 2026-05-25 GH Actions outage once the incident is `resolved`.
- Forward `data-testid` from `Button.svelte` for cleaner E2E selectors (currently the flows use role-based locators as a workaround).
