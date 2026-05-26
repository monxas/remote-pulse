import { test, expect, type Route } from '@playwright/test';
import { mockAdminAuth, mockSseSilent } from '../helpers/auth';
import { makeCommand } from '../helpers/fixtures';

/**
 * Flow 3 — Approve a pending command from /approvals.
 *
 * The approvals list seeds with one pending command. After clicking
 * "Approve" we expect `POST /v1/dash/approvals/:id/approve` to fire,
 * the success toast to surface, and the now-approved row to disappear
 * from the pending list (svelte-query refetches and the second response
 * returns an empty list).
 */

test.describe('flow: approve a pending command', () => {
  test('admin can approve a pending row and see it removed from the list', async ({ page }) => {
    await mockAdminAuth(page);
    await mockSseSilent(page);

    const pending = makeCommand({
      id: 'cmd-pending-1',
      host_id: 'host-x',
      host_hostname: 'rp-pending-host',
      issued_by: 'alice@test.local',
      command_type: 'shell',
      command_payload: { cmd: 'systemctl restart nginx', timeout_s: 30 },
      status: 'pending-approval',
    });

    let approveCalled = 0;

    await page.route('**/v1/dash/approvals/pending', (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          approvals: approveCalled === 0 ? [pending] : [],
        }),
      }),
    );

    await page.route(
      '**/v1/dash/approvals/cmd-pending-1/approve',
      (route: Route) => {
        if (route.request().method() !== 'POST') return route.fallback();
        approveCalled += 1;
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            ok: true,
            command: { ...pending, status: 'approved', approved_by: 'admin@test.local' },
          }),
        });
      },
    );

    // Side-effects of the approve mutation invalidate other caches.
    // Stub them with empty responses so the SPA does not show error
    // states for unrelated queries.
    await page.route('**/v1/dash/commands**', (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ commands: [], next_cursor: null }),
      }),
    );
    await page.route('**/v1/dash/audit**', (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ events: [], next_cursor: null }),
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
          pending_approvals: approveCalled === 0 ? 1 : 0,
          online_pct: 0,
          online_pct_24h_ago: 0,
        }),
      }),
    );

    await page.goto('approvals');
    await expect(page.getByRole('heading', { name: /^Approvals/ })).toBeVisible();

    // Pending row visible.
    await expect(page.getByText('rp-pending-host')).toBeVisible();
    await expect(page.getByText('systemctl restart nginx')).toBeVisible();

    // Approve. There is exactly one Approve button while the list has
    // one item; once it's clicked the row goes away.
    await page.getByRole('button', { name: 'Approve' }).click();

    await expect.poll(() => approveCalled).toBeGreaterThan(0);
    await expect(page.getByText('Approved').first()).toBeVisible(); // toast
    await expect(page.getByText('rp-pending-host')).toHaveCount(0);
    await expect(page.getByText('Nothing to approve. You are caught up.')).toBeVisible();
  });
});
