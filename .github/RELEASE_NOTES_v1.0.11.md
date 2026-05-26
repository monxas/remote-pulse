# Remote-Pulse v1.0.11 — mobile/touch polish + audit filters/export + Settings bulk ops

Patch release. No alembic migration.

## Highlights

- **Mobile/touch is now a first-class target.** The "mobile-first" claim from Phase 1 finally holds. Every interactive control honors a 44 px minimum tap target on coarse-pointer devices (Apple HIG / WCAG 2.5.5), inputs no longer trigger iOS auto-zoom, safe-area insets are respected (iPhone notch + iPad home indicator), modal dialogs become bottom-sheets on `<sm`, and pull-to-refresh lands on Fleet / Commands / Approvals / Audit.
- **Audit page is operationally useful.** Filter by actor (case-insensitive), action prefix (e.g. `settings.`), resource type, and date range with presets (Today / 24h / 7d / 30d / All / Custom). URL-persisted. Export filtered results as CSV or JSON via a new `GET /v1/dash/audit/export` endpoint (admin-only, 100k cap).
- **Settings bulk operations close the loop.** Multi-select checkboxes on Users + Groups tabs. Bulk role change, add-to-group, remove-from-group, grant permission, delete — for users. Bulk delete (only unused groups) — for groups. Safety guards: no self-delete, no self-demote, "DELETE" typing required for destructive ops, all-admins warning, common-group enforcement for remove.

## Changes

### Server

- `feat(server-audit)` `GET /v1/dash/audit` accepts: `actor` (case-insensitive), `action_prefix` (XOR with `action`, 422 if both), `resource_type`, `from_ts`/`to_ts` (aliases of `since`/`until`, `to_ts` exclusive, 422 if `from_ts >= to_ts`), `offset` pagination (XOR with `cursor`). Response envelope adds `total`, `limit`, `offset`, `has_more`; legacy `next_cursor` preserved.
- `feat(server-audit)` New `GET /v1/dash/audit/export` — admin-only, same filters, 100k cap, `?format=csv` (default) or `?format=json`. Content-Disposition header for browser download.
- No alembic needed — existing indexes from 008 cover all new query paths.

### Dashboard SPA — mobile/touch

- `app.css` adds `.touch-target` utility (auto-applies under `@media (hover: none) and (pointer: coarse)`), safe-area helpers (`pt-safe`/`pb-safe`/`pl-safe`/`pr-safe`/`mb-safe`), iOS auto-zoom kill (16px on inputs under coarse pointer), `scroll-margin-top: 5rem` on `:focus-visible`.
- `Button` primitive base class gains `touch-target` — every Button across the app grows to ≥44 px on touch without changing desktop chrome.
- `DialogContent` (`center` + `bottom` variants) becomes a bottom-sheet on `<sm` (rounded top corners, full width, `pb-safe`) and switches to centered modal on `sm+`. Close button grows to `h-9 w-9` on mobile.
- `NavBar`, `HostFilters`, `HostTable`, `BulkActionBar`, `WindowSelector`, `UserMenu`, `RecentActivityWidget`, `TabsTrigger`, Audit + Commands filter pills: each opts into `touch-target` (or wraps small targets in 44 px hit boxes).
- New `PullToRefresh.svelte` component (gesture wrapper, coarse-pointer-only, sqrt-style rubber-band damping, iOS-style indicator chip). Applied to Fleet / Commands / Approvals / Audit.
- `pull-to-refresh-state.ts` extracts pure helpers for DOM-free unit testing.
- Sticky table header was attempted then reverted (intercepted row-click hit-tests at desktop widths).

### Dashboard SPA — audit filters/export

- `/audit` page: filter bar (Actor input, Action prefix input debounced 250ms, Target type select, Range presets), Action pills (existing), Clear filters button, result count "Showing N of M events", Export dropdown (CSV / JSON via native `<a download>` to backend).
- URL persistence: `?actor`, `?action_prefix`, `?action` (multi), `?target_type`, `?range`, `?since`, `?until`.
- `audit-filters.ts` extracts pure helpers (`paramsFromSearch`, `RANGES`, `CLEAR_FILTERS_PATCH`) for unit testability.
- `api.ts` `buildAuditExportUrl(params, format)` helper.

### Dashboard SPA — Settings bulk

- New generic `createSelection<T extends string>()` in `selection.svelte.ts` (promoted from `host-selection.svelte.ts`, which becomes a thin back-compat wrapper).
- New `BulkUserActionBar.svelte` (5 intents: change role, add group, remove group, grant permission, delete).
- New `BulkGroupActionBar.svelte` (delete only, with `deletable` + `blockedNames` props).
- New `BulkUserDialogs.svelte` (single component with `BulkMode` enum hosting all 5 modals + per-user progress strip).
- New `bulk-user-ops.ts` (6 fan-out functions) + `bulk-group-ops.ts` (delete).
- Safety: no self-delete, no self-demote, "DELETE" typing required for destructive ops, all-admins warning, common-group enforcement, group-with-hosts pre-filter.

### Agent

- `chore` `__version__` + `pyproject.toml` → `1.0.11` (lockstep).

### Tests

- Backend: 18 new (11 audit filters + 7 audit export). Total new+regression suite: 91/91 green.
- Frontend unit: 105/105 (12 new for selection generic + bulk-user-ops + bulk-group-ops + audit-filters + api).
- Frontend E2E: 36/36 (10 new mobile.spec + 3 settings-bulk + 2 audit-filters + smoke specs unchanged).
- `npm run check`: 0 errors / 0 warnings.

### Bugfix

- `fix(tests)` `test_dash_audit_filters.py` + `test_dash_audit_export.py` had `from tests.test_dash_phase2 import ...` (absolute) which fails pytest collection. Changed to relative `from test_dash_phase2 import ...`.

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
# {"status":"healthy","version":"1.0.11"}
```

In the dashboard:
- Open on a phone or tablet → buttons noticeably bigger, modals become bottom-sheets.
- Open `/audit` → filter bar visible above the timeline. Pick "Last 7 days" + an actor → URL updates. Click Export → CSV / JSON menu.
- Open `/settings` → Users tab has leftmost checkboxes. Select 2+ → floating bar with 5 bulk actions.

## Known follow-ups (v1.0.12+)

- Swipe-to-reveal row actions on Audit / Commands (deferred per the mobile-polish agent's value/risk call).
- Lighthouse mobile measurements (the agent didn't have an LXC 280 path from its worktree; can be re-measured locally).
- Operator-with-host.delete-grant client-side gate visibility (currently admin-only in UI).
- Cancel 5 stale `release.yml` runs once GH Actions incident closes.
