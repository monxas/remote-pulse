import { test, expect, type Route } from '@playwright/test';
import { mockAdminAuth, mockSseSilent } from '../helpers/auth';
import { makeHost, makeCommand, makeOverview } from '../helpers/fixtures';

/**
 * Flow — bulk issue command from the Fleet table.
 *
 * Walks: select-all checkbox → action bar visible → "Issue command" →
 * pick shell type → enter payload → submit → assert per-host result
 * rows + the right number of POST /v1/dash/commands fan-out requests.
 *
 * Two scenarios:
 *   1. happy-path: all 3 hosts return 201, success toast.
 *   2. partial-failure: one host returns 403, results table shows the
 *      403 row with the friendlier permission-denied message.
 */

test.describe('flow: bulk issue command on selected hosts', () => {
  test('admin can select all and issue on N hosts', async ({ page }) => {
    await mockAdminAuth(page);
    await mockSseSilent(page);

    const hosts = [
      makeHost({ id: 'h1', hostname: 'rp-alpha', group_name: 'prod' }),
      makeHost({ id: 'h2', hostname: 'rp-beta', group_name: 'prod' }),
      makeHost({ id: 'h3', hostname: 'rp-gamma', group_name: 'prod' }),
    ];

    let issuedCount = 0;
    const issuedHostIds: string[] = [];

    await page.route('**/v1/dash/hosts**', (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ hosts, groups: ['prod'] }),
      }),
    );

    await page.route('**/v1/dash/overview', (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(makeOverview({ total: 3, online: 3, online_pct: 100 })),
      }),
    );

    await page.route('**/v1/dash/commands**', (route: Route) => {
      const req = route.request();
      if (req.method() === 'POST' && /\/v1\/dash\/commands(\?|$)/.test(req.url())) {
        const body = req.postDataJSON() as { host_ids: string[] };
        issuedCount += 1;
        issuedHostIds.push(...body.host_ids);
        const cmd = makeCommand({
          id: `cmd-${body.host_ids[0]}`,
          host_id: body.host_ids[0]!,
          status: 'pending-approval',
        });
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ commands: [cmd] }),
        });
      }
      if (req.method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ commands: [], next_cursor: null }),
        });
      }
      return route.fallback();
    });

    await page.goto('/');
    await expect(page.getByRole('heading', { name: 'Fleet' })).toBeVisible();
    await expect(page.getByTestId('hosts-table')).toBeVisible();

    // Toggle the header checkbox -> selects every visible row.
    await page.getByTestId('select-all-hosts').click();

    // Action bar appears with the right count.
    const bar = page.getByTestId('bulk-action-bar');
    await expect(bar).toBeVisible();
    await expect(bar).toContainText('3');

    // Open the bulk dialog.
    await page.getByTestId('bulk-issue-command').click();
    await expect(page.getByRole('dialog')).toBeVisible();
    await expect(page.getByTestId('bulk-host-count')).toHaveText('3');

    // Step 1: pick shell command type.
    await expect(page.getByText('Step 1 of 4')).toBeVisible();
    await page.getByTestId('bulk-cmd-type-shell').click();

    // Step 2: fill payload.
    await expect(page.getByText('Step 2 of 4')).toBeVisible();
    await page.getByLabel('Shell command').fill('uptime');
    await page.getByTestId('bulk-next').click();

    // Step 3: reason+approval → submit.
    await expect(page.getByText('Step 3 of 4')).toBeVisible();
    await page.getByTestId('bulk-submit').click();

    // Step 4: results table. Wait for all 3 fan-out POSTs to settle.
    await expect(page.getByText('Step 4 of 4')).toBeVisible();
    await expect.poll(() => issuedCount).toBe(3);

    // Each host gets a per-host row marked as `issued`.
    for (const h of hosts) {
      const row = page.getByTestId(`bulk-result-${h.hostname}`);
      await expect(row).toHaveAttribute('data-status', 'success');
    }

    // Success toast fires once all are settled.
    await expect(page.getByText(/3 commands issued/)).toBeVisible();

    // Each fan-out call targets exactly one host id.
    expect(new Set(issuedHostIds)).toEqual(new Set(['h1', 'h2', 'h3']));
  });

  test('partial-failure: one host returns 403, others 201', async ({ page }) => {
    await mockAdminAuth(page);
    await mockSseSilent(page);

    const hosts = [
      makeHost({ id: 'h1', hostname: 'rp-alpha', group_name: 'prod' }),
      makeHost({ id: 'h2', hostname: 'rp-beta', group_name: 'prod' }),
      makeHost({ id: 'h3', hostname: 'rp-gamma', group_name: 'prod' }),
    ];

    await page.route('**/v1/dash/hosts**', (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ hosts, groups: ['prod'] }),
      }),
    );
    await page.route('**/v1/dash/overview', (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(makeOverview({ total: 3, online: 3, online_pct: 100 })),
      }),
    );

    await page.route('**/v1/dash/commands**', (route: Route) => {
      const req = route.request();
      if (req.method() === 'POST') {
        const body = req.postDataJSON() as { host_ids: string[] };
        const targetId = body.host_ids[0]!;
        if (targetId === 'h2') {
          return route.fulfill({
            status: 403,
            contentType: 'application/json',
            body: JSON.stringify({ detail: 'no command.issue grant' }),
          });
        }
        const cmd = makeCommand({
          id: `cmd-${targetId}`,
          host_id: targetId,
          status: 'pending-approval',
        });
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ commands: [cmd] }),
        });
      }
      if (req.method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ commands: [], next_cursor: null }),
        });
      }
      return route.fallback();
    });

    await page.goto('/');
    await expect(page.getByTestId('hosts-table')).toBeVisible();

    // Pick each row individually (exercises per-row checkboxes).
    await page.getByTestId('select-host-rp-alpha').click();
    await page.getByTestId('select-host-rp-beta').click();
    await page.getByTestId('select-host-rp-gamma').click();

    await expect(page.getByTestId('bulk-action-bar')).toContainText('3');
    await page.getByTestId('bulk-issue-command').click();

    await page.getByTestId('bulk-cmd-type-shell').click();
    await page.getByLabel('Shell command').fill('uptime');
    await page.getByTestId('bulk-next').click();
    await page.getByTestId('bulk-submit').click();

    // Per-host outcomes settle.
    await expect(page.getByTestId('bulk-result-rp-alpha')).toHaveAttribute(
      'data-status',
      'success',
    );
    await expect(page.getByTestId('bulk-result-rp-beta')).toHaveAttribute('data-status', 'error');
    await expect(page.getByTestId('bulk-result-rp-gamma')).toHaveAttribute(
      'data-status',
      'success',
    );

    // The error row surfaces the friendlier permission message.
    await expect(page.getByTestId('bulk-result-rp-beta')).toContainText(/Permission denied/);

    // Partial-failure toast.
    await expect(page.getByText(/2 commands issued, 1 failed/)).toBeVisible();
  });
});
