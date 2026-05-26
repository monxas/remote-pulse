# Remote-Pulse v1.0.8 — host delete + last perm gates + sortable tables + a11y 1.00

Patch release. Operator action required: `alembic upgrade head` (010, FK cascade on commands.host_id).

## Highlights

- **`DELETE /v1/dash/hosts/{id}` shipped + `host.delete` permission live.** Hosts can be deleted from the API (UI button is a follow-up). Cascade behavior: heartbeats, commands, ssh_keys, agent_versions, metric_samples all dropped with the host. Blocks (409) if the host is the canary of an active deploy. 404 wins over 403 so access-denied looks like missing.
- **Permission gate coverage 100% for the 5 ALLOWED_ACTIONS.** `command.issue` now gates `/v1/dash/commands` POST + retry (was admin/operator role-gated). `enroll.revoke` is a new separate action — operators can hold `enroll.create` without `enroll.revoke` (issuer vs revoker pattern).
- **`/settings` a11y to 1.00.** CardTitle default level h3→h2 (semantic fix, no `aria-level` hack), `text-default` added for explicit color baseline, `text-danger` callers switched to `text-danger-text` (red-11, contrast 6.5:1). All 4 Lighthouse-audited routes now report a11y=1.00.
- **Sortable + searchable tables.** Fleet, Settings Groups, Settings Users. Click headers to cycle ASC→DESC→unsort with `aria-sort` indicators. Search box with debounce + reset. Sort + query persisted in URL search params for shareable links. New `table-state.svelte.ts` rune-based helper + `SortableHeader` + `TableSearch` components.

## Changes

### Server

- `feat(server-permissions)` `dash_commands.py` `issue_command` (`POST /v1/dash/commands`) now gates on `command.issue` scoped to host group. Old `role in {admin, operator}` gate removed.
- `feat(server-permissions)` `dash_commands.py` `retry_command` (`POST /v1/dash/commands/{id}/retry`) gates on `command.issue` scoped to the original command's host group.
- `feat(server-permissions)` `enroll.revoke` added to `ALLOWED_ACTIONS`. `DELETE /v1/dash/enroll/links/{jti}` gates on it (scope = enrollment.group_name). `require_admin` removed.
- `feat(server-host)` New `DELETE /v1/dash/hosts/{host_id}` in `dash_api.py`. Loads host via `filter_hosts_by_user_groups` (404 collapse to prevent existence probing), permission check, 409 canary block, explicit delete of TimescaleDB hypertables (heartbeats, metric_samples), then `db.delete(host)` triggers cascade for the rest. Emits `host.delete` audit row.
- `chore(server-models)` `Command.host_id` ORM mapping gets `ondelete="CASCADE"` to match new FK.
- `chore(server-alembic)` `010_host_delete_cascade.py` swaps `commands.host_id` FK from `NO ACTION` to `ON DELETE CASCADE`.
- `chore(server-tests)` `conftest.py` enables `PRAGMA foreign_keys=ON` on SQLite so cascade assertions actually exercise the constraint.
- `test(server)` +18 permission-gap tests (`test_permissions_dash_gaps.py`) + 8 host delete tests (`test_dash_host_delete.py`).

### Dashboard SPA

- `fix(web-a11y)` `card-title.svelte` default `level` 3→2; `text-default` added.
- `fix(web-a11y)` 3 callers swap `text-danger` → `text-danger-text` (red-9 → red-11).
- `feat(web-tables)` `table-state.svelte.ts` exposes `createTableState()` factory — `{ view, sortKey, sortDir, query, toggleSort, setQuery, reset, ariaSort }` with URL sync via `$app/state.page` + `goto({ replaceState: true })`. Pure `applyTableState()` + `nextSortState()` helpers are exported for unit testing.
- `feat(web-tables)` `SortableHeader.svelte` (chevron, `aria-sort`, three-state cycle) + `TableSearch.svelte` (debounced input + reset).
- `feat(web-tables)` Fleet table (`HostTable.svelte`), Settings Groups, Settings Users now sortable + searchable.
- `feat(web-permissions)` `api.ts` `PermissionAction` union + `ALL_PERMISSION_ACTIONS` array include `'enroll.revoke'`.
- `test(web)` +15 unit tests for table-state + 3 Playwright tests covering URL contract, DOM reorder, aria-sort cycle.

### Agent

- `chore` `__version__` + `pyproject.toml` → `1.0.8` (lockstep with server).

## Lighthouse scores (local, vite preview, desktop preset)

| Page | perf | a11y | bp | seo |
|---|---|---|---|---|
| Fleet | **1.00** | **1.00** | **1.00** | **1.00** |
| Hosts | **1.00** | **1.00** | **1.00** | **1.00** |
| Audit | **1.00** | **1.00** | **1.00** | **1.00** |
| Settings | **1.00** | **1.00** | **1.00** | **1.00** |

All 4 categories at 1.00 across all 4 routes. v1.0.7 settings was 0.94 a11y; now 1.00.

## Upgrade

```sh
cd /opt/rp/source
git pull
cd server
set -a; source /etc/rp/server.env; set +a
sudo -u rp env POSTGRES_URL="$POSTGRES_URL" JWT_SECRET="$JWT_SECRET" \
    /opt/rp/source/server/.venv/bin/alembic upgrade head
cd ..
scripts/build_dashboard.sh
systemctl restart rp-server
```

Verify the FK cascade is in place:
```sh
sudo -u postgres psql -d remote_pulse -c "
  SELECT conname, confdeltype FROM pg_constraint
  WHERE conname = 'commands_host_id_fkey';
"
# confdeltype = 'c' (CASCADE)
```

## Verifying

```sh
curl -sS https://rp.monxas.casa/health
# {"status":"healthy","version":"1.0.8"}
```

API contracts to spot-check after deploy:

```sh
# As admin: list permissions for a user, should include enroll.revoke + host.delete
curl -sS https://rp.monxas.casa/v1/dash/settings/users/<uuid>/permissions \
    --cookie "..." | jq '.allowed_actions'
# ["command.issue", "command.approve", "host.delete", "enroll.create", "enroll.revoke"]
```

## Known follow-ups (v1.0.9+)

- Delete host button + confirmation modal on `hosts/[id]/+page.svelte` (backend ships first; UI follows).
- 1 pre-existing Playwright flake on `enroll-magic-link.spec.ts` — unrelated to this release, verified flaky on `main` pre-merge.
- Cancel 5 stale `release.yml` runs once GH Actions incident closes.
- Decision pending on bulk operations UI (multi-select hosts → bulk command, bulk role change in Settings).
