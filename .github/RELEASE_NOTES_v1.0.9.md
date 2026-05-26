# Remote-Pulse v1.0.9 — delete host UI + bulk operations + SSE polish

Patch release. No alembic migration. Forward-compatible SSE wire format addition (existing clients keep working).

## Highlights

- **Delete host UI** on the host detail page. AlertDialog-style confirmation, admin-gated, navigates to the fleet on success. Closes a latent bug in `api.ts request()` that mishandled `204 No Content` responses (also affected `deleteSettingsUser/Group`, `revokeEnrollLink`, `revokeUserPermission` — all silently broken before).
- **Multi-select + bulk issue command** from the Fleet table. Tri-state checkbox header, floating action bar appears when ≥1 selected, BulkIssueCommandDialog fires `N` parallel requests and reports per-host status (success/failure/permission-denied) in a 3-column results table.
- **SSE auto-reconnect with gap replay.** Exponential backoff (1→2→4→8→16→30s, max 10 retries, 5s stable-window reset). Server-side keeps a 128-event ring buffer; reconnects pass `Last-Event-ID` and the server emits one synthetic `gap` event containing everything missed. New `RecentActivityWidget` in the topbar (bell icon + unread badge + dropdown of last 10 events with click-through navigation). Toasts auto-raise only on important events (`command.failed`/`timeout`/`rejected`, `approval.created`, `host.status_change → offline`).

## Changes

### Server

- `feat(server-events)` `EventBus` extended with monotonic ids + 128-event in-memory ring buffer. New `subscribe_with_id()` API alongside back-compat `subscribe()`.
- `feat(server-stream)` `/v1/dash/stream` honors `Last-Event-ID` request header (set automatically by browsers on EventSource reconnect) and emits a single synthetic `gap` event with all missed events before resuming the live tail. If the ring has rolled past the client's id, the gap is empty but the event still fires so the SPA exits its reconnecting state.
- `test(server)` 5 new tests in `test_events_replay.py` covering replay ordering, `last_id=0` semantics, ring cap, monotonic id ordering, and back-compat with the legacy `subscribe()` API.

### Dashboard SPA

- `feat(web-host)` `hosts/[id]/+page.svelte` adds a "Danger zone" section at the bottom with a `Delete host` button (admin-gated). Opens `DeleteHostDialog` (role="alertdialog", spinner while in-flight, focus trap inherited from bits-ui).
- `fix(web-api)` `api.ts request()` now correctly handles `204 No Content` — was crashing downstream `.toFixed`/`.length` calls. Silently broken since the first delete-flavored endpoint shipped.
- `feat(web-queries)` `createDeleteHostMutation` snapshots every `['hosts', …]` cache key, optimistically filters out the deleted id, rolls back on error, invalidates fleet/overview/audit/host on settle.
- `feat(web-fleet)` `HostTable.svelte` adds a checkbox column (header + per-row + mobile cards), tri-state via `use:indeterminate` action. `+page.svelte` owns the selection rune (`createHostSelection()` backed by `SvelteSet`) and wires `BulkActionBar` + `BulkIssueCommandDialog`.
- `feat(web-bulk)` `BulkIssueCommandDialog.svelte` (4-step wizard: type → payload → reason → results). `bulk-dispatch.ts` fans out N requests via `Promise.all`, rewrites 403s to "Permission denied", aggregates into success/error/warning toast.
- `feat(web-sse)` `sse.svelte.ts` rewritten as a robust bridge: exponential backoff, max-retries → `failed` state with persistent destructive toast, stable-window reset, idempotent cleanup. Handles incoming `gap` events transparently.
- `feat(web-notifications)` `RecentActivityWidget.svelte` in the topbar (between `ThemeToggle` and `UserMenu`) — bell + numeric badge (capped at "9+"), click → dropdown of last 10 events, persisted `lastSeenTs` in localStorage. `LiveToasts.svelte` raises destructive/warning toasts only on the curated set of important events.
- `feat(web-live)` `LiveBadge.svelte` shows real-time bridge state — Online / Reconnecting / Offline.
- `test(web)` 3 unit tests for backoff sequence, 5 for host selection, 5 for bulk dispatch, 3 for optimistic patches. 2 E2E for bulk command, 2 for realtime widget + toast.

### Agent

- `chore` `__version__` + `pyproject.toml` → `1.0.9` (lockstep with server).

## Lighthouse scores (unchanged)

All 4 categories still 1.00 across all 4 audited routes.

## Upgrade

```sh
cd /opt/rp/source
git pull
scripts/build_dashboard.sh
systemctl restart rp-server
```

No alembic migration this release.

## Verifying

```sh
curl -sS https://rp.monxas.casa/health
# {"status":"healthy","version":"1.0.9"}
```

In the dashboard:
- Open a host detail page → "Danger zone" appears with delete button (if admin).
- Open Fleet → leftmost checkboxes appear. Select 2+ hosts → floating action bar shows.
- Reload the page → SSE reconnects automatically, badge in topbar shows recent events.

## Known follow-ups (v1.0.10+)

- **Short-code enrollment** in progress (replaces the giant `?token=eyJ...` URLs with a memorable 6-char code, 5min default TTL). Ships as v1.0.10.
- Bulk operations on Settings Users tab (multi-select role change / group toggle) — captured as follow-up.
- Operator-with-host.delete-grant should see the delete button (currently admin-only client-side; backend remains source of truth).
- Cancel 5 stale `release.yml` runs once GH Actions incident closes.
