import { test, expect, type Route } from '@playwright/test';
import { mockAdminAuth, mockSseSilent } from '../helpers/auth';
import { makeCommand } from '../helpers/fixtures';

/**
 * Flow 6 — Retry a failed command from the /commands list.
 *
 * The failed row is rendered by `CommandRow`. Clicking the row toggle
 * expands the detail panel which shows stderr + a Retry button. The
 * Retry mutation POSTs `/v1/dash/commands/{id}/retry`; on success the
 * page invalidates the commands cache, the success toast surfaces, and
 * a new pending row appears in the list.
 */

test.describe('flow: retry a failed command', () => {
  test('admin can retry a failed command and see the new pending row', async ({ page }) => {
    await mockAdminAuth(page);
    await mockSseSilent(page);

    const failed = makeCommand({
      id: 'cmd-failed-1',
      host_id: 'host-x',
      host_hostname: 'rp-host-x',
      command_type: 'shell',
      command_payload: { cmd: 'systemctl status nginx', timeout_s: 30 },
      status: 'failed',
      exit_code: 1,
      stdout: '',
      stderr: 'nginx: command not found',
      duration_ms: 250,
      issued_by: 'alice@test.local',
      approved_by: 'admin@test.local',
      human_approved: true,
      completed_at: new Date().toISOString(),
    });

    const retried = makeCommand({
      id: 'cmd-retry-1',
      host_id: failed.host_id,
      host_hostname: failed.host_hostname,
      command_type: failed.command_type,
      command_payload: failed.command_payload,
      status: 'pending-approval',
      issued_by: 'admin@test.local',
    });

    let retryCount = 0;
    let listIncludesRetried = false;

    await page.route('**/v1/dash/commands/cmd-failed-1/retry', (route: Route) => {
      if (route.request().method() !== 'POST') return route.fallback();
      retryCount += 1;
      listIncludesRetried = true;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(retried),
      });
    });

    // GET /v1/dash/commands — start with the failed row only, add the new
    // pending row after the retry mutation succeeds.
    await page.route('**/v1/dash/commands**', (route: Route) => {
      const req = route.request();
      const url = req.url();
      if (req.method() !== 'GET') return route.fallback();
      if (!/\/v1\/dash\/commands(\?|$)/.test(url)) return route.fallback();
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          commands: listIncludesRetried ? [retried, failed] : [failed],
          next_cursor: null,
        }),
      });
    });

    await page.route('**/v1/dash/hosts**', (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ hosts: [], groups: [] }),
      }),
    );
    await page.route('**/v1/dash/overview', (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          total: 0,
          online: 0,
          stale: 0,
          offline: 0,
          pending_approvals: 0,
          online_pct: 0,
          online_pct_24h_ago: 0,
        }),
      }),
    );

    await page.goto('commands');
    await expect(page.getByRole('heading', { name: 'Commands' })).toBeVisible();

    const failedRow = page.getByTestId('command-row').filter({
      has: page.locator('[data-command-id="cmd-failed-1"]'),
    });
    // The above filter is redundant when the row itself has that attr;
    // fall back to a direct attribute selector for clarity.
    const row = page.locator('[data-testid="command-row"][data-command-id="cmd-failed-1"]');
    await expect(row).toBeVisible();
    void failedRow; // silence ts-unused

    // Expand the row — the toggle button is inside the row.
    await row.getByTestId('command-row-toggle').click();

    // stderr surfaces in the expanded detail panel.
    await expect(row.getByText('nginx: command not found')).toBeVisible();

    // Retry button only appears in the expanded panel for retryable rows.
    await row.getByTestId('command-retry-btn').click();

    // POST fired + toast + new pending row appears.
    await expect.poll(() => retryCount).toBe(1);
    await expect(page.getByText('Command re-issued')).toBeVisible();

    const newRow = page.locator('[data-testid="command-row"][data-command-id="cmd-retry-1"]');
    await expect(newRow).toBeVisible();
    // Original failed row still present, retried row now sitting above it.
    await expect(page.getByTestId('command-row')).toHaveCount(2);
  });
});
