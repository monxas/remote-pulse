import { test, expect, type Route } from '@playwright/test';
import { mockAdminAuth, mockSseSilent } from '../helpers/auth';
import { makeHost, makeOverview } from '../helpers/fixtures';

/**
 * Flow 1 — Login + Fleet overview + Host detail drill-down.
 *
 * Verifies the happy path a freshly-authenticated admin sees on first
 * paint: overview metric cards, host table with mixed statuses, then
 * click-through into the host detail page where the metrics tab renders
 * a timeseries chart.
 */

test.describe('flow: login -> fleet -> host detail', () => {
  test('admin sees overview, host rows, and can open a host detail page', async ({ page }) => {
    await mockAdminAuth(page);
    await mockSseSilent(page);

    const hosts = [
      makeHost({
        id: 'host-online',
        hostname: 'rp-prod-1',
        group_name: 'prod',
        status: 'online',
        last_seen_seconds_ago: 3,
      }),
      makeHost({
        id: 'host-stale',
        hostname: 'rp-prod-2',
        group_name: 'prod',
        status: 'stale',
        last_seen_seconds_ago: 120,
      }),
      makeHost({
        id: 'host-offline',
        hostname: 'rp-family-1',
        group_name: 'family',
        status: 'offline',
        last_seen_seconds_ago: 9_000,
      }),
    ];

    await page.route('**/v1/dash/overview', (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(
          makeOverview({ total: 3, online: 1, stale: 1, offline: 1, online_pct: 33.3 }),
        ),
      }),
    );

    await page.route('**/v1/dash/hosts**', (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ hosts, groups: ['prod', 'family'] }),
      }),
    );

    // Build a tiny timeseries fixture matching the
    // `TimeseriesPayload` contract. The host-detail page reads
    // `cpu_pct`/`mem_pct` arrays of the same length as `ts`.
    const nowS = Math.floor(Date.now() / 1000);
    const ts = Array.from({ length: 12 }, (_, i) => nowS - (11 - i) * 30);
    await page.route('**/v1/dash/hosts/*/timeseries**', (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          host_id: 'host-online',
          window_s: 300,
          bucket_s: 30,
          ts,
          cpu_pct: ts.map((_, i) => 10 + i),
          mem_pct: ts.map(() => 42),
          load_1m: ts.map(() => 0.2),
        }),
      }),
    );

    // ---- Fleet overview ----
    await page.goto('./');

    await expect(page.getByRole('heading', { name: 'Fleet' })).toBeVisible();

    // Metric cards. The Fleet page renders 4 `MetricCard`s; we assert
    // the two whose hint copy is unique to the metric tiles (the word
    // "approvals" also appears in the nav, hence not asserted here).
    await expect(page.getByText('fleet size')).toBeVisible();
    await expect(page.getByText('60-180s')).toBeVisible(); // "Stale" hint

    // Host rows. Both the desktop table and the mobile card list render
    // the hostname (responsive CSS hides one), so we count via the
    // desktop row's role="link" + aria-label which is unique per host.
    await expect(page.getByRole('link', { name: 'Open host rp-prod-1' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Open host rp-prod-2' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Open host rp-family-1' })).toBeVisible();

    // Status badges — `HostStatusBadge` has role="status" + an aria-label
    // that includes the status word. Use the role + name filter so we
    // don't collide with the status filter `<option>` tags.
    await expect(page.getByRole('status').filter({ hasText: 'Online' }).first()).toBeVisible();
    await expect(page.getByRole('status').filter({ hasText: 'Stale' }).first()).toBeVisible();
    await expect(page.getByRole('status').filter({ hasText: 'Offline' }).first()).toBeVisible();

    // ---- Drill-down into a host ----
    // The desktop table renders each row with role="link" and an
    // aria-label "Open host <hostname>". That gives us a stable handle
    // that doesn't depend on column markup.
    await page.getByRole('link', { name: 'Open host rp-prod-1' }).click();

    await page.waitForURL(/\/dash-next\/hosts\/host-online/);
    await expect(page.getByRole('heading', { name: 'rp-prod-1' })).toBeVisible();

    // The "Group" / "OS" / etc. metadata strip renders the host meta.
    await expect(page.getByText('Group')).toBeVisible();
    await expect(page.getByText('linux')).toBeVisible();

    // Metrics tab is the default. The chart section heading + the
    // "Current values" card both surface once the host + timeseries
    // queries resolve.
    await expect(page.getByRole('tab', { name: 'Metrics' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Current values' })).toBeVisible();
  });
});
