# Remote-Pulse v1.0.12 — statistics dashboard + webhooks + browser notifications

Operator action required: `alembic upgrade head` (012, adds `webhooks` table).

## Highlights

- **Statistics dashboard.** New `/dash-next/stats` page with 4 KPI cards (total hosts / fleet uptime % / commands success rate / total audit events), daily commands stacked bar, per-host uptime list, top audit actions + actors. Range selector (24h / 7d / 30d / 90d) URL-synced. Server endpoint `/v1/dash/stats` aggregates everything in ~8 queries — TimescaleDB `time_bucket()` over hypertables, with a SQLite-fallback path so the test fixture works without TimescaleDB.
- **Webhooks system.** New `webhooks` table + `WebhookDispatcher` that subscribes to the event bus and POSTs to configured URLs with HMAC-SHA256 signature. Retry [0s, 1s, 5s, 30s] = 4 attempts with 10s timeout. Auto-disables after 10 consecutive failures. Per-row deliveries log (JSONB sliding window, cap 20 — debug aid; canonical audit lives in `audit_events`). Admin-only `/dash-next/webhooks` page with create modal that reveals the secret once.
- **Browser notifications (opt-in, in-app).** New Settings tab "Notifications" with three permission states (default / granted / denied). Six event opt-ins with sensible defaults: Command failed + Approval requested ON, host status changes OFF, audit events OFF (admin-only). When the dashboard tab is backgrounded and an opted-in SSE event arrives, the browser fires a native `Notification`. Tab focused → existing toasts handle it. No service worker, no VAPID — the in-app path is 90% of the value with 20% of the scope, and the opt-in persistence is reusable if we layer push later.

## Changes

### Server

- `feat(server-stats)` New router `dash_stats.py`. `GET /v1/dash/stats?range=24h|7d|30d|90d` returns fleet / commands (with by_type + daily) / heartbeats / uptime_per_host / audit_summary. Scoped by `accessible_groups`. Postgres path uses TimescaleDB `time_bucket()`; SQLite path uses `strftime('%s', ts) / 60` so tests don't need a hypertable. 9 backend tests.
- `feat(server-webhooks)` Alembic 012 adds `webhooks(id, name, url, secret, event_filter[], group_filter[], enabled, created_by, created_at, last_fired_at, last_status_code, last_error, failure_count, recent_deliveries jsonb)` with partial index `WHERE enabled = true`.
- `feat(server-webhooks)` New `webhooks.py` module with `WebhookDispatcher` (event bus subscriber, fan-out via `asyncio.create_task`, shared `httpx.AsyncClient` for pooling, filter matching for `*` / `prefix.` / exact, group filter from `payload["group_name"]`).
- `feat(server-webhooks)` New router `dash_webhooks.py` (admin-only): list / create (secret returned once) / detail / patch / delete / test / deliveries.
- `feat(server-webhooks)` URL validator: `https://` always allowed, `http://` only for localhost / 127 / RFC1918 (avoids accidental exfiltration).
- `feat(server-webhooks)` HMAC-SHA256 signature header `X-RP-Signature-256: sha256=<hex>` over canonical JSON body. Plus `X-RP-Event-Type`, `X-RP-Delivery-Id`, `X-RP-Timestamp`.
- 17 webhook tests + 1 conftest extension for the `'[]'::jsonb` default on SQLite.

### Dashboard SPA

- `feat(web-stats)` `/dash-next/stats` page with KPI cards + 4 inline-SVG charts (daily commands stacked bar, uptime per host, top actions, top actors). Range pill selector with URL sync. PullToRefresh wrap. Mobile-first (cards 2×2 in `<sm`, charts stacked).
- `feat(web-webhooks)` `/dash-next/webhooks` admin page with table + new-webhook modal + one-time secret reveal dialog (TriangleAlert icon, copy-to-clipboard, "I have saved the secret" dismiss). Enabled toggle uses shadcn Switch. Per-row Test + Delete + Edit buttons.
- `feat(web-notifications)` New Settings tab "Notifications" with `NotificationsToggle.svelte` (Enable / Enabled ✓ / Blocked states) + per-event opt-in checkboxes. `LiveNotifications.svelte` mounted in `+layout.svelte` listens to SSE and fires `new Notification(...)` when tab backgrounded + opted in. `notifications-state.ts` exports pure helpers (`shouldFireNotification`, `classifySseEvent`, `loadOptIns`, `saveOptIns`) with 18 vitest cases.
- New nav links: "Stats" (between Audit and Settings) and "Webhooks" (admin section).

### Tests

- Server: +26 tests (9 stats + 17 webhooks).
- Frontend unit: +18 notification helpers. 150/150 vitest green.
- E2E: +2 stats specs + 1 webhook spec + 3 notification specs (Playwright not executed locally in those branches; specs structurally consistent with existing flows).
- `npm run check`: 0 errors / 0 warnings.

### Agent

- `chore` `__version__` + `pyproject.toml` → `1.0.12` (lockstep).

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
# {"status":"healthy","version":"1.0.12"}

# webhooks table created
sudo -u postgres psql -d remote_pulse -c "\d webhooks" | head -20
```

In the dashboard:
- `/dash-next/stats` — KPI cards + charts for the last 7 days.
- `/dash-next/webhooks` (admin) — create a test webhook pointing at https://webhook.site or an n8n endpoint, click Test, watch the request arrive.
- `/dash-next/settings` → Notifications tab → enable + tick "Command failed" → simulate a failed command, switch to another tab → browser notification fires.

## Known follow-ups (v1.0.13+)

- VAPID push notifications (background-capable, tab-closed). The in-app opt-in persistence + event classifier already in place are reusable.
- Continuous aggregates / materialized views for `/v1/dash/stats` if the dataset grows past ~100k heartbeats.
- Webhook deliveries view in the UI (currently the JSON sliding window is exposed via `GET /v1/dash/webhooks/{id}/deliveries` but no page renders it).
- Cancel the 5 stale `release.yml` runs once GH Actions incident closes.
