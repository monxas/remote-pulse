# Remote-Pulse v1.0.13 — audit retention + webhook deliveries UI + saved views

Operator action required: `alembic upgrade head` (013, adds `audit_retention_config` singleton).

## Highlights

- **Audit retention policy.** New `audit_retention_config` singleton + background asyncio task that purges `audit_events` older than the configured window every 24h. Default 90 days, bounds [7, 3650]. Admin-tunable from a new Retention tab in Settings (current days + last-purge relative time + manual purge button). Three Prometheus metrics expose lifetime stats. New `idx_audit_events_ts` index supports the range-delete.
- **Webhook deliveries log UI.** New `/dash-next/webhooks/[id]/deliveries` page showing the sliding-window log (last 20 attempts) with status badges, attempt counters, expandable error details, and a Retry button on failed rows. Auto-refresh every 10s (pauseable, off when tab not focused). Auto-disabled webhooks show a badge + "Reset failures" button to clear `failure_count` and re-enable.
- **Saved views.** Generic `createSavedViewsStore<T>()` helper + `SavedViewsSwitcher.svelte` UI. Factory views ship out-of-the-box (4 fleet + 4 audit + 3 commands, 11 total) and operators can save / pin / rename / delete their own. URL search params round-trip into localStorage by scope. Plain JSON import/export for cross-browser portability — no server endpoint.

## Changes

### Server

- `feat(server-audit-retention)` Alembic 013 adds `audit_retention_config(id PK CHECK=1, retention_days, enabled, last_purge_at, last_purge_count, updated_by, updated_at)`, seeded `(1, 90, true)`. Also adds `idx_audit_events_ts ON audit_events(ts)` for the range delete.
- `feat(server-audit-retention)` `audit_retention.py` module with `purge_old_audit_events()` (uses `synchronize_session=False` + `RETURNING id` for precise count without a follow-up select) + `retention_loop()` background task (24h tick, started in `lifespan()` and cancelled on shutdown, 60s initial delay).
- `feat(server-audit-retention)` New router `dash_retention.py` (admin-only): GET / PATCH / POST purge-now. PATCH emits `audit.retention.config_updated` with before/after diff; purge-now emits `audit.retention.manual_purge` *before* the delete so the trail of who-triggered survives the deletion of all other events.
- `feat(server-audit-retention)` 3 new Prometheus metrics: `rp_audit_retention_purge_total{result}` (counter), `rp_audit_retention_events_deleted_total` (counter), `rp_audit_events_total` (gauge refreshed on scrape).
- `feat(server-webhooks)` `POST /v1/dash/webhooks/{id}/deliveries/{delivery_id}/retry` — re-fires the recorded delivery via `WebhookDispatcher.dispatch_retry()`. New record gets `retry_of: <original_delivery_id>` marker. Audit emit: `webhook.delivery.retried`.
- `feat(server-webhooks)` `POST /v1/dash/webhooks/{id}/reset-failures` — clears `failure_count` + `enabled = true`. Returns updated `WebhookSummary` for client-side cache patch. Audit emit: `webhook.failures_reset`.

### Dashboard SPA

- `feat(web-audit-retention)` Settings → Retention tab with `RetentionCard.svelte`. Shows current days + last-purge relative time. Range input + slider 7-3650, enabled toggle, Save/Reset, Purge-now button gated behind confirm Dialog. `retention-format.ts` extracts pure `formatRelativeTime` for unit testing (9 cases).
- `feat(web-webhook-deliveries)` New route `/dash-next/webhooks/[id]/deliveries`. Table with Time / Event / Status / Attempt / Delivery ID / Error / Actions columns. Per-row Retry button on failed rows. Errors >60 chars truncate with "View full" expand. Retry-of rows show a small badge. Auto-refresh toggle in the header.
- `feat(web-webhook-deliveries)` `/dash-next/webhooks/+page.svelte` table now shows `Auto-disabled` badge when `failure_count >= 10` + `Reset failures` action button. Links to the deliveries page per webhook.
- `feat(web-saved-views)` `saved-views.svelte.ts` exports `createSavedViewsStore(scope, pathname)` rune-backed factory + pure helpers (`paramsFromUrl`, `paramsEqual`, `paramsToSearch`, `slugify`, `loadUserViews`, `persistUserViews`, `FACTORY_VIEWS`). `SavedViewsSwitcher.svelte` renders a factory pill row + custom-views dropdown with Save / Manage / Import / Export.
- `feat(web-saved-views)` Applied to `/audit`, `/`, `/commands` pages.
- New query keys: `qk.retention()`, `qk.webhookDeliveries(id)`. New mutations: retention CRUD, retry delivery, reset failures.

### Agent

- `chore` `__version__` + `pyproject.toml` → `1.0.13` (lockstep).

### Tests

- Server: +13 audit-retention + +7 webhook deliveries = 20 new. 159/159 pre-existing pass.
- Frontend unit: +9 retention-format + +16 saved-views = 25 new. 159/159 total green.
- E2E: +2 audit-retention + +2 webhook-deliveries + +3 saved-views.
- `npm run check`: 0 errors / 0 warnings.

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

## Verifying

```sh
curl -sS https://rp.monxas.casa/health
# {"status":"healthy","version":"1.0.13"}

sudo -u postgres psql -d remote_pulse -c "SELECT retention_days, enabled, last_purge_at FROM audit_retention_config;"
```

In the dashboard:
- `/dash-next/settings` → Retention tab → adjust days, save, watch the audit log gain a `audit.retention.config_updated` event.
- `/dash-next/webhooks/[id]/deliveries` → see the per-webhook log; click Retry on a failed row.
- `/dash-next/audit` and `/` → SavedViewsSwitcher above the filters → click a factory view ("Today", "Offline only") or save current as a custom view.

## Known follow-ups (v1.0.14+)

- VAPID push notifications (background-capable when tab closed). In-app opt-in persistence + classifier from v1.0.12 are reusable.
- Continuous aggregates / materialized views for `/v1/dash/stats` if dataset grows beyond ~100k heartbeats.
- Cancel 5 stale `release.yml` runs once GH Actions incident closes.
- Audit retention metrics — `audit_events_total` gauge could be a sparkline on the Stats page.
- Saved views: server-side sync (optional opt-in) for cross-device persistence beyond JSON import/export.
