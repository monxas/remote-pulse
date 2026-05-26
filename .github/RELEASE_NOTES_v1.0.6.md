# Remote-Pulse v1.0.6 — permission gates expansion + Button rest props + 3 E2E flows

Patch release. No breaking changes. No alembic migration.

## Highlights

- **Row-level ACL extended to 2 more actions.** `POST /v1/dash/approvals/{id}/approve` and `.../reject` now require `command.approve` (scope = command's host group). `POST /v1/dash/enroll/links` now requires `enroll.create` (scope = request body group). Operators without a matching grant get 403; admins still bypass. `host.delete` stays reserved in `ALLOWED_ACTIONS` — the endpoint doesn't exist yet.
- **`Button.svelte` properly forwards rest props.** The v1.0.5 fix only forwarded `aria-label` + `title`. This release adds `{...rest}` on the `<button>` branch (matching the `<a>` branch), restoring `data-testid`, `name`, `value`, `formaction`, etc. Closes the bug noted independently by two parallel agents in v1.0.5.
- **3 new E2E flows under Playwright:** `host-detail` (header, OS metadata, uPlot canvas, time window switch, current-values card, issue-command dialog), `command-retry` (failed row → stderr expand → Retry → new pending), `audit-timeline` (mixed synthetic + real events, DESC order, action chip filter, expand metadata).
- **6 E2E selectors restored to `data-testid`** now that `Button` forwards them. Tests stop using role-based workarounds in the spots where the UI has explicit testids.
- **UI quality improvements**: Issue-command button + dialog on host detail page, `data-testid` attrs on `CommandRow` + `AuditEvent` for stable testing.

## Changes

### Server

- `feat(server-permissions)` `dash_commands.py`: removed legacy `role not in {admin, operator}` gate in `_resolve_approval`; replaced with `user_has_permission(db, user, "command.approve", scope=command.host.group_name)` after the 404 check (so missing resources still 404, not 403).
- `feat(server-permissions)` `dash_enroll.py`: removed `require_admin` dependency from `create_enroll_link`; replaced with per-`group_name` `user_has_permission(db, user, "enroll.create", scope=group_name)` check. `require_admin` retained on list + revoke.
- `feat(server-permissions)` 12 new tests covering admin bypass, deny, wildcard scope, scoped match, scope mismatch for each wired action.

### Dashboard SPA

- `fix(web-button)` `Button.svelte` `<button>` branch spreads `{...rest}` (after the explicit type/onclick/disabled/aria-label/title bindings). Type definition extended to merge `HTMLAnchorAttributes & HTMLButtonAttributes`.
- `test(web-button)` 3 vitest unit tests via `@testing-library/svelte` covering both `<button>` and `<a>` branches with rest props + overrides.
- `chore(web-vitest)` `vite.config.ts` adds `resolve.conditions: ['browser']` + `server.deps.inline: ['@testing-library/svelte']` so vitest jsdom doesn't pull Svelte's server entry.
- `feat(web-e2e)` 3 new flow specs (`host-detail`, `command-retry`, `audit-timeline`). All mock auth + relevant `/v1/dash/*` endpoints.
- `feat(web)` `hosts/[id]/+page.svelte` adds an Issue-command button + `IssueCommandDialog` wired with the current host as the initial selection.
- `chore(web)` `CommandRow.svelte`, `AuditEvent.svelte`: added `data-testid` + `data-*` attrs for stable test selectors.
- 6 selectors in `settings.spec.ts`, `enroll.spec.ts`, `flows/enroll-magic-link.spec.ts` switched back from role-based to `getByTestId`.

### Agent

- `chore` `__version__` + `pyproject.toml` → `1.0.6` (lockstep with server).

## Upgrade

```sh
cd /opt/rp/source
git pull
scripts/build_dashboard.sh
systemctl restart rp-server
```

(No alembic migration required this release.)

## Verifying

```sh
curl -sS https://rp.monxas.casa/health
# {"status":"healthy","version":"1.0.6"}
```

Try the permission gate:
```sh
# As an operator without command.approve grant on the host's group:
# POST /v1/dash/approvals/{id}/approve → 403
# After grant via /v1/dash/settings/users/{id}/permissions:
# Same call → 200
```

## Known follow-ups (v1.0.7+)

- Lighthouse perf push + OIDC test-bypass for measuring authed pages (separate parallel work in progress — will ship as v1.0.7).
- Wire `command.issue` on `/v1/dash/commands` POST + retry (duplicates the `/v1/admin/commands` semantics; same enum value).
- Implement `DELETE /v1/dash/hosts/{id}` and wire `host.delete` permission.
- Cancel 5 stale `release.yml` workflow runs when GH Actions incident closes.
