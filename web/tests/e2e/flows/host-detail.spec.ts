import { test, expect, type Route } from '@playwright/test';
import { mockAdminAuth, mockSseSilent } from '../helpers/auth';
import { makeHost } from '../helpers/fixtures';

/**
 * Flow 5 — Host detail page (Phase 2).
 *
 * Verifies the metrics tab renders for a single host:
 *  - header (hostname + OS/Group badges)
 *  - timeseries chart (uPlot canvas mounted inside the chart container)
 *  - WindowSelector switch triggers a refetch with the new `window` param
 *  - "Current values" card surfaces latest CPU/mem/load
 *  - "Issue command" button opens the IssueCommandDialog
 */

test.describe('flow: host detail page', () => {
  test('admin sees timeseries, window selector refetches, and can open the issue-command dialog', async ({
    page,
  }) => {
    await mockAdminAuth(page);
    await mockSseSilent(page);

    const host = makeHost({
      id: 'host-detail-1',
      hostname: 'rp-detail-1',
      group_name: 'prod',
      status: 'online',
      os_family: 'linux',
      current: { cpu_pct: 42.7, mem_pct: 67.3, load_1m: 1.25, uptime_s: 3_600 * 24 },
    });

    // The Fleet/Hosts query is also pinged by createHostsQuery used inside
    // IssueCommandDialog; return the host so the dialog renders something.
    await page.route('**/v1/dash/hosts**', (route: Route) => {
      const url = route.request().url();
      // Single-host detail endpoint: `/v1/dash/hosts/<id>` (no trailing query).
      if (/\/v1\/dash\/hosts\/host-detail-1(\?|$)/.test(url)) {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(host),
        });
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ hosts: [host], groups: ['prod'] }),
      });
    });

    // Track which `window` value the SPA asked for.
    const tsWindowCalls: string[] = [];
    const nowS = Math.floor(Date.now() / 1000);
    await page.route('**/v1/dash/hosts/*/timeseries**', (route: Route) => {
      const url = new URL(route.request().url());
      tsWindowCalls.push(url.searchParams.get('window') ?? '');
      const ts = Array.from({ length: 24 }, (_, i) => nowS - (23 - i) * 60);
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          host_id: host.id,
          window_s: 1_440,
          bucket_s: 60,
          ts,
          cpu_pct: ts.map((_, i) => 30 + (i % 10)),
          mem_pct: ts.map(() => 65),
          load_1m: ts.map(() => 1.2),
        }),
      });
    });

    await page.route('**/v1/dash/overview', (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          total: 1,
          online: 1,
          stale: 0,
          offline: 0,
          pending_approvals: 0,
          online_pct: 100,
          online_pct_24h_ago: 100,
        }),
      }),
    );

    await page.goto(`hosts/${host.id}`);

    // Header + metadata strip
    await expect(page.getByRole('heading', { name: 'rp-detail-1' })).toBeVisible();
    await expect(page.getByText('Group')).toBeVisible();
    // OS family rendered in the metadata strip.
    await expect(page.getByText('linux').first()).toBeVisible();

    // Metrics tab is the default, the chart container has role="img"
    // and renders the uPlot canvas inside once data arrives.
    await expect(page.getByRole('tab', { name: 'Metrics' })).toBeVisible();
    const chart = page.getByRole('img', { name: 'CPU & Memory' });
    await expect(chart).toBeVisible();
    // uPlot mounts a <canvas> inside the container; wait for it.
    await expect(chart.locator('canvas')).toHaveCount(1);

    // "Current values" card with latest numbers (formatted to 1 dp / 2 dp).
    await expect(page.getByRole('heading', { name: 'Current values' })).toBeVisible();
    await expect(page.getByText('42.7%')).toBeVisible();
    await expect(page.getByText('67.3%')).toBeVisible();
    await expect(page.getByText('1.25')).toBeVisible();

    // Click the 1h time window: WindowSelector is a radiogroup, each
    // option is a role=radio with the literal text label.
    await page.getByRole('radio', { name: '1h', exact: true }).click();
    // URL receives `?window=1h` and the SPA refetches the timeseries.
    await expect(page).toHaveURL(/[?&]window=1h\b/);
    await expect.poll(() => tsWindowCalls.includes('1h')).toBe(true);

    // Issue command button opens the multi-step dialog.
    await page.getByTestId('host-issue-command-btn').click();
    await expect(page.getByRole('dialog')).toBeVisible();
    // The dialog's step indicator surfaces immediately on open.
    await expect(page.getByText(/Step \d of 5/)).toBeVisible();
  });

  test('admin can delete a host: confirm modal -> DELETE -> redirect to fleet', async ({
    page,
  }) => {
    await mockAdminAuth(page);
    await mockSseSilent(page);

    const host = makeHost({
      id: 'host-delete-1',
      hostname: 'rp-delete-1',
      group_name: 'prod',
    });

    let hostFleetGone = false;
    let deleteCallCount = 0;

    await page.route('**/v1/dash/hosts/host-delete-1', (route: Route) => {
      if (route.request().method() === 'DELETE') {
        deleteCallCount += 1;
        hostFleetGone = true;
        return route.fulfill({ status: 204, body: '' });
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(host),
      });
    });

    await page.route('**/v1/dash/hosts**', (route: Route) => {
      const url = route.request().url();
      if (/\/v1\/dash\/hosts\/host-delete-1(\?|$)/.test(url)) {
        // Handled by the more specific route above; defer just in case.
        return route.fallback();
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          hosts: hostFleetGone ? [] : [host],
          groups: ['prod'],
        }),
      });
    });

    await page.route('**/v1/dash/hosts/*/timeseries**', (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          host_id: host.id,
          window_s: 300,
          bucket_s: 10,
          ts: [],
          cpu_pct: [],
          mem_pct: [],
          load_1m: [],
        }),
      }),
    );

    await page.route('**/v1/dash/overview', (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          total: hostFleetGone ? 0 : 1,
          online: hostFleetGone ? 0 : 1,
          stale: 0,
          offline: 0,
          pending_approvals: 0,
          online_pct: 100,
          online_pct_24h_ago: 100,
        }),
      }),
    );

    await page.goto(`hosts/${host.id}`);

    await expect(page.getByRole('heading', { name: 'rp-delete-1' })).toBeVisible();

    // Danger zone visible to admins
    const deleteBtn = page.getByTestId('host-delete-btn');
    await expect(deleteBtn).toBeVisible();

    // Modal opens on click
    await deleteBtn.click();
    const modal = page.getByTestId('host-delete-dialog');
    await expect(modal).toBeVisible();
    await expect(modal.getByText(/Delete this host\?/)).toBeVisible();
    await expect(modal.getByText(/rp-delete-1/)).toBeVisible();

    // Confirm: fires DELETE and lands on the fleet overview
    await page.getByTestId('host-delete-confirm').click();
    await expect.poll(() => deleteCallCount).toBe(1);
    await expect(page).toHaveURL(/\/dash-next\/?$/);
  });

  test('admin can cancel the delete modal: no DELETE request fires', async ({ page }) => {
    await mockAdminAuth(page);
    await mockSseSilent(page);

    const host = makeHost({
      id: 'host-delete-2',
      hostname: 'rp-delete-2',
      group_name: 'prod',
    });

    let deleteCallCount = 0;
    await page.route('**/v1/dash/hosts/host-delete-2', (route: Route) => {
      if (route.request().method() === 'DELETE') {
        deleteCallCount += 1;
        return route.fulfill({ status: 204, body: '' });
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(host),
      });
    });

    await page.route('**/v1/dash/hosts**', (route: Route) => {
      const url = route.request().url();
      if (/\/v1\/dash\/hosts\/host-delete-2(\?|$)/.test(url)) {
        return route.fallback();
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ hosts: [host], groups: ['prod'] }),
      });
    });

    await page.route('**/v1/dash/hosts/*/timeseries**', (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          host_id: host.id,
          window_s: 300,
          bucket_s: 10,
          ts: [],
          cpu_pct: [],
          mem_pct: [],
          load_1m: [],
        }),
      }),
    );

    await page.route('**/v1/dash/overview', (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          total: 1,
          online: 1,
          stale: 0,
          offline: 0,
          pending_approvals: 0,
          online_pct: 100,
          online_pct_24h_ago: 100,
        }),
      }),
    );

    await page.goto(`hosts/${host.id}`);
    await expect(page.getByRole('heading', { name: 'rp-delete-2' })).toBeVisible();

    await page.getByTestId('host-delete-btn').click();
    const modal = page.getByTestId('host-delete-dialog');
    await expect(modal).toBeVisible();
    await page.getByTestId('host-delete-cancel').click();
    await expect(modal).not.toBeVisible();
    // Settle a beat to make sure nothing fired async.
    await page.waitForTimeout(150);
    expect(deleteCallCount).toBe(0);
    await expect(page).toHaveURL(/\/hosts\/host-delete-2/);
  });

  test('non-admin operator does not see the delete button', async ({ page }) => {
    await mockAdminAuth(page, { user_role: 'operator', user_email: 'ops@test.local' });
    await mockSseSilent(page);

    const host = makeHost({
      id: 'host-delete-3',
      hostname: 'rp-delete-3',
      group_name: 'prod',
    });

    await page.route('**/v1/dash/hosts**', (route: Route) => {
      const url = route.request().url();
      if (/\/v1\/dash\/hosts\/host-delete-3(\?|$)/.test(url)) {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(host),
        });
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ hosts: [host], groups: ['prod'] }),
      });
    });

    await page.route('**/v1/dash/hosts/*/timeseries**', (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          host_id: host.id,
          window_s: 300,
          bucket_s: 10,
          ts: [],
          cpu_pct: [],
          mem_pct: [],
          load_1m: [],
        }),
      }),
    );

    await page.route('**/v1/dash/overview', (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          total: 1,
          online: 1,
          stale: 0,
          offline: 0,
          pending_approvals: 0,
          online_pct: 100,
          online_pct_24h_ago: 100,
        }),
      }),
    );

    await page.goto(`hosts/${host.id}`);
    await expect(page.getByRole('heading', { name: 'rp-delete-3' })).toBeVisible();
    await expect(page.getByTestId('host-delete-btn')).toHaveCount(0);
  });
});
