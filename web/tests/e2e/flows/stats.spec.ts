import { test, expect, type Route } from '@playwright/test';
import { mockAdminAuth, mockSseSilent } from '../helpers/auth';

/**
 * Flow — /dash-next/stats page (feat/stats-dashboard).
 *
 * Covers:
 * - KPI cards render with values returned by ``/v1/dash/stats``.
 * - Range selector pushes ``?range=...`` into the URL and re-issues the
 *   request with the new value.
 * - Charts mount as <svg> elements when data is present.
 */

const STATS_PAYLOAD_7D = {
  range: '7d',
  fleet: { total_hosts: 8, online_now: 7, offline_now: 1, uptime_percent: 98.4 },
  commands: {
    total: 142,
    succeeded: 138,
    failed: 3,
    pending: 1,
    success_rate: 0.972,
    by_type: [
      { type: 'shell', count: 120 },
      { type: 'script', count: 22 },
    ],
    daily: [
      { day: '2026-05-20', issued: 18, succeeded: 18, failed: 0 },
      { day: '2026-05-21', issued: 22, succeeded: 21, failed: 1 },
      { day: '2026-05-22', issued: 30, succeeded: 30, failed: 0 },
      { day: '2026-05-23', issued: 25, succeeded: 24, failed: 1 },
      { day: '2026-05-24', issued: 19, succeeded: 19, failed: 0 },
      { day: '2026-05-25', issued: 14, succeeded: 13, failed: 1 },
      { day: '2026-05-26', issued: 14, succeeded: 13, failed: 0 },
    ],
  },
  heartbeats: {
    total: 1872834,
    per_host_avg_per_min: 1.02,
    stale_events: 0,
    offline_events: 1,
  },
  uptime_per_host: [
    { hostname: 'rp-server', uptime_percent: 99.99, downtime_minutes: 1 },
    { hostname: 'pmx-50', uptime_percent: 99.8, downtime_minutes: 20 },
    { hostname: 'pmx-51', uptime_percent: 97.5, downtime_minutes: 252 },
  ],
  audit_summary: {
    total_events: 234,
    by_action: [
      { action: 'settings.permission.grant', count: 88 },
      { action: 'command.issued', count: 50 },
    ],
    by_actor: [
      { actor: 'admin@x', count: 88 },
      { actor: 'ops@x', count: 40 },
    ],
  },
};

const STATS_PAYLOAD_24H = {
  ...STATS_PAYLOAD_7D,
  range: '24h',
  commands: {
    ...STATS_PAYLOAD_7D.commands,
    total: 18,
    succeeded: 18,
    failed: 0,
    success_rate: 1.0,
  },
};

test.describe('flow: /stats page', () => {
  test('renders KPI cards and charts with the mocked payload', async ({ page }) => {
    await mockAdminAuth(page);
    await mockSseSilent(page);

    await page.route('**/v1/dash/stats**', (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(STATS_PAYLOAD_7D),
      }),
    );

    await page.goto('stats');

    // Header is present.
    await expect(page.getByRole('heading', { name: 'Statistics' })).toBeVisible();

    // KPI cards rendered.
    const kpiSection = page.getByTestId('stats-kpi-cards');
    await expect(kpiSection).toBeVisible();
    await expect(kpiSection).toContainText('8'); // total hosts
    await expect(kpiSection).toContainText('98.40%'); // uptime
    await expect(kpiSection).toContainText('97.2%'); // success rate
    await expect(kpiSection).toContainText('234'); // audit events

    // Charts mount as SVGs / scoped containers.
    await expect(page.getByTestId('stats-daily-chart')).toBeVisible();
    await expect(page.getByTestId('stats-uptime-chart')).toBeVisible();
    await expect(page.getByTestId('stats-actions-chart')).toBeVisible();
    await expect(page.getByTestId('stats-actors-chart')).toBeVisible();

    // Daily chart renders SVG with 7 daily buckets → 14 <rect> bars (ok+fail).
    const svgRects = page.getByTestId('stats-daily-chart').locator('svg rect');
    await expect(svgRects).toHaveCount(14);

    // Uptime list shows host bars (display rounded to 1 decimal).
    await expect(page.getByTestId('stats-uptime-chart')).toContainText('rp-server');
    await expect(page.getByTestId('stats-uptime-chart')).toContainText('100.0%');
  });

  test('range selector updates the URL and refetches', async ({ page }) => {
    await mockAdminAuth(page);
    await mockSseSilent(page);

    let lastRange: string | null = null;
    await page.route('**/v1/dash/stats**', (route: Route) => {
      const url = new URL(route.request().url());
      lastRange = url.searchParams.get('range');
      const body = lastRange === '24h' ? STATS_PAYLOAD_24H : STATS_PAYLOAD_7D;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(body),
      });
    });

    await page.goto('stats');
    await expect(page.getByTestId('stats-kpi-cards')).toBeVisible();
    await expect.poll(() => lastRange).toBe('7d');

    // Click the 24h pill.
    await page.getByTestId('stats-range-24h').click();

    // URL should now carry ?range=24h.
    await expect.poll(() => new URL(page.url()).searchParams.get('range')).toBe('24h');
    // Server got the new range.
    await expect.poll(() => lastRange).toBe('24h');
    // KPI updates to the 24h numbers.
    await expect(page.getByTestId('stats-kpi-cards')).toContainText('100.0%'); // 18/18 success
  });
});
