import { test, expect, type Route } from '@playwright/test';
import { mockAdminAuth, mockSseSilent } from '../helpers/auth';
import { makeHost } from '../helpers/fixtures';

/**
 * Flow 9 — Table-state polish (sort + search, URL-persisted).
 *
 * Validates the v1.0.8 polish work on the Fleet table on the home page:
 *  - Clicking a sortable column header writes `h_sort` + `h_dir` to the URL.
 *  - A second click flips the direction; a third clears it.
 *  - The visible row order matches the sort.
 *
 * For coverage of search, the existing `HostFilters` already debounces a
 * URL update for the `q` param — we don't re-test that here, but we do
 * smoke-test that sort + filter co-exist via separate URL params.
 */

const BASE = '/dash-next';

async function mockOverview(page: import('@playwright/test').Page): Promise<void> {
  await page.route('**/v1/dash/overview', (route: Route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        total: 3,
        online: 3,
        stale: 0,
        offline: 0,
        unknown: 0,
        online_pct: 100,
        online_pct_24h_ago: 100,
        pending_approvals: 0,
      }),
    }),
  );
}

test.describe('flow: sortable host table', () => {
  test('clicking a column header cycles asc → desc → unsorted and reorders rows', async ({
    page,
  }) => {
    await mockAdminAuth(page);
    await mockSseSilent(page);
    await mockOverview(page);

    const hosts = [
      makeHost({ id: 'h-1', hostname: 'beta-host', group_name: 'prod' }),
      makeHost({ id: 'h-2', hostname: 'alpha-host', group_name: 'staging' }),
      makeHost({ id: 'h-3', hostname: 'gamma-host', group_name: 'prod' }),
    ];

    await page.route('**/v1/dash/hosts**', (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ hosts, groups: ['prod', 'staging'] }),
      }),
    );

    await page.goto(`${BASE}/`, { waitUntil: 'networkidle' });

    const table = page.locator('[data-testid="hosts-table"]');
    await expect(table).toBeVisible();

    // Initial server order: beta, alpha, gamma.
    let rows = table.locator('tbody tr');
    await expect(rows.nth(0)).toContainText('beta-host');
    await expect(rows.nth(1)).toContainText('alpha-host');
    await expect(rows.nth(2)).toContainText('gamma-host');

    // Click "Host" header → asc.
    const hostHeader = table.locator('th button', { hasText: 'Host' });
    await hostHeader.click();
    await expect(page).toHaveURL(/h_sort=hostname/);
    await expect(page).toHaveURL(/h_dir=asc/);

    rows = table.locator('tbody tr');
    await expect(rows.nth(0)).toContainText('alpha-host');
    await expect(rows.nth(1)).toContainText('beta-host');
    await expect(rows.nth(2)).toContainText('gamma-host');

    // Second click → desc.
    await hostHeader.click();
    await expect(page).toHaveURL(/h_dir=desc/);
    rows = table.locator('tbody tr');
    await expect(rows.nth(0)).toContainText('gamma-host');
    await expect(rows.nth(2)).toContainText('alpha-host');

    // Third click → unsorted (params removed).
    await hostHeader.click();
    await expect(page).not.toHaveURL(/h_sort=/);
    await expect(page).not.toHaveURL(/h_dir=/);
    rows = table.locator('tbody tr');
    await expect(rows.nth(0)).toContainText('beta-host');
  });

  test('aria-sort attribute follows the cycle for screen readers', async ({ page }) => {
    await mockAdminAuth(page);
    await mockSseSilent(page);
    await mockOverview(page);

    const hosts = [
      makeHost({ id: 'h-1', hostname: 'alpha', group_name: 'prod' }),
      makeHost({ id: 'h-2', hostname: 'beta', group_name: 'prod' }),
    ];
    await page.route('**/v1/dash/hosts**', (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ hosts, groups: ['prod'] }),
      }),
    );

    await page.goto(`${BASE}/`, { waitUntil: 'networkidle' });

    const table = page.locator('[data-testid="hosts-table"]');
    const hostHeaderTh = table.locator('th', { has: page.locator('button', { hasText: 'Host' }) });

    // Initially unsorted.
    await expect(hostHeaderTh).toHaveAttribute('aria-sort', 'none');

    await hostHeaderTh.locator('button').click();
    await expect(hostHeaderTh).toHaveAttribute('aria-sort', 'ascending');

    await hostHeaderTh.locator('button').click();
    await expect(hostHeaderTh).toHaveAttribute('aria-sort', 'descending');

    await hostHeaderTh.locator('button').click();
    await expect(hostHeaderTh).toHaveAttribute('aria-sort', 'none');
  });
});

test.describe('flow: settings table search + sort', () => {
  test('search query filters rows and persists to URL', async ({ page }) => {
    await mockAdminAuth(page);
    await mockSseSilent(page);

    await page.route('**/v1/dash/settings/groups', (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          groups: [
            { name: 'prod', description: 'production fleet', host_count: 5, user_count: 3 },
            { name: 'staging', description: 'pre-prod env', host_count: 2, user_count: 1 },
            { name: 'family', description: 'home machines', host_count: 4, user_count: 2 },
          ],
        }),
      }),
    );
    await page.route('**/v1/dash/settings/users', (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ users: [] }),
      }),
    );

    await page.goto(`${BASE}/settings`, { waitUntil: 'networkidle' });

    const table = page.locator('[data-testid="groups-table"]');
    await expect(table).toBeVisible();
    await expect(table.locator('tbody tr')).toHaveCount(3);

    const search = page.locator('[data-testid="groups-search-input"]');
    await search.fill('prod');
    // Debounce is 200 ms — wait for the URL to update.
    await expect(page).toHaveURL(/g_q=prod/, { timeout: 2000 });

    // 'prod' matches both 'prod' and 'staging' (which has 'pre-prod' in desc).
    await expect(table.locator('tbody tr')).toHaveCount(2);

    // Reset clears query + sort.
    await page.locator('[data-testid="groups-search-reset"]').click();
    await expect(page).not.toHaveURL(/g_q=/);
    await expect(table.locator('tbody tr')).toHaveCount(3);
  });
});
