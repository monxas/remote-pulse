# Remote-Pulse v1.0.15 — Six polish-tier QoL closures

Patch release. No alembic migration. Closes every "Known follow-up"
from v1.0.14's release notes — the six polish-tier gaps surfaced by
the same QoL audit that produced v1.0.14's three critical fixes.

## Why this release exists

v1.0.14 closed the three highest-friction gaps (group_filter pills,
Retention `DELETE` typing, host.delete capability gate). The audit also
identified six smaller — but still "operator has to type when they
should be picking" — gaps. v1.0.15 closes them so the polish floor of
the dashboard is uniform.

## Highlights

- **Enrollment QR code.** The magic-link result card now renders a QR
  code of the Unix install command next to the hero code. Operators on
  one device can scan from another (Family Hub tablet → phone, laptop →
  friend's phone) without a chat-app round-trip.
- **PermissionsDialog scope as chips.** Replaces the free-text
  Input + `<datalist>` with a wildcard `*` toggle + per-group chip
  selector. Multi-select fans out one POST per group on submit (the
  server's grant endpoint accepts one scope per call). Typing scopes
  with a hyphen typo silently produced never-matching grants — chips
  reading from the live groups list close that hole.
- **Bulk command "Cancel remaining".** Mid-flight Cancel button on the
  BulkIssueCommandDialog results step. In-flight requests are allowed
  to settle (so the server-issued command rows don't leak as
  "did-it-or-didn't-it"); the queued tail is dropped and rendered as a
  new `cancelled` chip. The dispatcher moved from unbounded
  `Promise.all` to a bounded worker pool (concurrency=4) — only this
  shape makes cancel actually skip work.
- **Webhook integration templates.** "Quick fill" chips for Discord /
  Slack / n8n drop a placeholder URL + sensible default event filters
  into the empty form. Templates are non-destructive — any operator-
  typed value is preserved. URL field is auto-focused + selected so
  the operator lands on the `{ID}/{TOKEN}` placeholders.
- **Audit-events sparkline on /stats.** New `audit_summary.daily`
  per-day bucket on `/v1/dash/stats`; the Audit events KPI card now
  renders a 60×20 inline-SVG sparkline. When retention purges old
  events, the leftmost cells drop visibly — operators get a no-clicks-
  required signal that retention is doing something.
- **Audit page action chips sorted by frequency.** Pills order
  highest-count first (from the 30d window's `audit_summary.by_action`),
  ties alphabetical, zero-count actions at the tail. Stable across
  range changes — flipping the on-page range filter doesn't reshuffle
  the chip list while the operator is mid-pick. Inline count badge on
  each chip when count > 0.

## Changes

### Server

- `feat(server-stats)` `audit_summary.daily: list[{day, count}]` added
  to `/v1/dash/stats`. Same shape as `commands.daily`. Postgres path
  uses `time_bucket('1 day', ...)`; SQLite path uses `date()`.
- `chore(server)` `__version__` + `pyproject.toml` → `1.0.15`.

### Dashboard SPA

- `feat(web-enroll)` Enroll result card renders a QR code (data-URL PNG)
  of the Unix `install_url` next to the hero code. Dep: `qrcode@1.5.4`
  (~6 KB gz). New `data-testid` selectors: `enroll-qr`, `enroll-qr-img`.
- `feat(web-settings)` PermissionsDialog scope picker is a wildcard
  toggle + per-group chips. Multi-select fans out one grant per scope.
  New testids: `perm-scope-wildcard`, `perm-scope-{group}`,
  `perm-grant-submit`, `perm-multi-hint`.
- `feat(web-commands)` BulkIssueCommandDialog gains a "Cancel remaining"
  button on the submitting step. `dispatchBulk` accepts an
  `AbortSignal` + bounded `concurrency` (default 4); queued rows that
  hit the abort surface as `status: 'cancelled'`. Toast summarises
  `N issued, M failed, K cancelled`. New testid:
  `bulk-cancel-remaining`, `bulk-cancelled-count`.
- `feat(web-webhooks)` New-webhook modal shows three "Quick fill" chips
  (Discord / Slack / n8n). Template apply is pure + tested
  (`integration-templates.ts`). New testids: `wh-templates`,
  `wh-template-{key}`.
- `feat(web-stats)` Audit events KPI card replaces the
  `MetricCard` with a bespoke Card that includes an inline-SVG
  sparkline below the count. New testids: `stats-audit-card`,
  `stats-audit-total`, `stats-audit-sparkline`.
- `feat(web-audit)` Action filter pills sorted by recent-30d
  frequency; sort helper extracted to `audit-filters.ts` and unit-
  tested. Inline count badge on each chip when count > 0.

### Agent

- `chore` `__version__` + `pyproject.toml` → `1.0.15` (lockstep with
  server).

## Tests

- `web/src/lib/commands/bulk-dispatch.test.ts` gains two new
  cancellation tests: signal aborts queued tail mid-run; pre-aborted
  signal cancels every host without firing any request.
- `web/src/routes/audit/audit-filters.test.ts` gains three tests for
  the new `sortActionsByFrequency` helper.
- `web/src/routes/webhooks/integration-templates.test.ts` (new file)
  covers the pure `applyTemplate` contract — preserves operator
  typing, treats `['*']` as untouched, returns fresh arrays, doesn't
  mutate inputs.
- Total unit tests: 194 (was 175). All green. `svelte-check`: 0 errors.
- Server `tests/test_dash_stats.py`: 9 passed (unchanged — the new
  `daily` field carries a default `[]` so it's additive).

## Upgrade

```sh
cd /opt/rp/source
git pull
scripts/build_dashboard.sh
systemctl restart rp-server
```

No alembic migration. The new `audit_summary.daily` field defaults to
`[]` on legacy clients.

## Verifying

```sh
curl -sS https://rp.monxas.casa/health
# {"status":"healthy","version":"1.0.15"}

# /v1/dash/stats now ships `audit_summary.daily` (admin)
curl -sS 'https://rp.monxas.casa/v1/dash/stats?range=7d' \
  --cookie "rp_session=..." | jq '.audit_summary.daily | length'
```

In the dashboard:

- `/enroll` → generate a code → QR appears next to the hero code.
- `/settings` → Users → ⋯ → Permissions → scope chips replace the
  free-text input.
- Fleet table → select 5+ hosts → Issue command → submit → "Cancel
  remaining" button appears mid-flight.
- `/webhooks` → "New webhook" → three Quick fill chips above the URL.
- `/stats` → Audit events card now has a sparkline below the count.
- `/audit` → action filter pills ordered by recent frequency, count
  badge on the right.
