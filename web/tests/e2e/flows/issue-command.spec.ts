import { test, expect, type Route } from '@playwright/test';
import { mockAdminAuth, mockSseSilent } from '../helpers/auth';
import { makeCommand, makeHost } from '../helpers/fixtures';

/**
 * Flow 2 — Issue a command from the /commands page.
 *
 * Walks through the 5-step `IssueCommandDialog`: pick host -> pick
 * command type (shell) -> enter payload -> review -> submit. After the
 * `POST /v1/dash/commands` resolves we expect the new row in the list
 * (after svelte-query invalidates the `commands` cache) and a
 * `toast.success('Command issued')` notification.
 */

test.describe('flow: issue a command', () => {
  test('admin can issue a shell command and see the new pending row', async ({ page }) => {
    await mockAdminAuth(page);
    await mockSseSilent(page);

    const host = makeHost({ id: 'host-issue', hostname: 'rp-target', group_name: 'prod' });
    const newCmd = makeCommand({
      id: 'cmd-new',
      host_id: host.id,
      host_hostname: host.hostname,
      command_type: 'shell',
      command_payload: { cmd: 'systemctl status nginx', timeout_s: 60 },
      status: 'pending-approval',
    });

    let issuedCount = 0;
    // Track whether the commands list has been re-fetched after the
    // mutation so we can return the row that the user just created.
    let listIncludesNewCmd = false;

    await page.route('**/v1/dash/hosts**', (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ hosts: [host], groups: ['prod'] }),
      }),
    );

    await page.route('**/v1/dash/commands**', (route: Route) => {
      const req = route.request();
      const url = req.url();
      const method = req.method();

      // POST /v1/dash/commands — issue path. After the first POST the
      // GET list starts returning the new row, simulating the server
      // having persisted the command before svelte-query refetches.
      if (method === 'POST' && /\/v1\/dash\/commands(\?|$)/.test(url)) {
        issuedCount += 1;
        listIncludesNewCmd = true;
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ commands: [newCmd] }),
        });
      }

      if (method === 'GET' && /\/v1\/dash\/commands(\?|$)/.test(url)) {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            commands: listIncludesNewCmd ? [newCmd] : [],
            next_cursor: null,
          }),
        });
      }

      return route.fallback();
    });

    // The Commands page reads overview indirectly via cache invalidation;
    // not strictly required to mock, but the SPA fires it once on mount
    // through the layout — return a stub so it does not hit network.
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

    await page.goto('commands');
    await expect(page.getByRole('heading', { name: 'Commands' })).toBeVisible();

    // Empty-state CTA -> open dialog
    await page.getByRole('button', { name: 'New command' }).click();
    await expect(page.getByRole('dialog')).toBeVisible();
    await expect(page.getByText('Step 1 of 5')).toBeVisible();

    // Step 1: pick the only host fixture, advance.
    await page.getByLabel('Select rp-target').check();
    await page.getByRole('button', { name: /^Next/ }).click();

    // Step 2: choose `shell`. The button label is "Shell".
    await expect(page.getByText('Step 2 of 5')).toBeVisible();
    await page.getByRole('button', { name: /^Shell/ }).click();

    // Step 3: payload. Auto-advanced into step 3 by `choose()`.
    await expect(page.getByText('Step 3 of 5')).toBeVisible();
    await page.getByLabel('Shell command').fill('systemctl status nginx');
    await page.getByRole('button', { name: /^Next/ }).click();

    // Step 4: reason / approval — leave defaults.
    await expect(page.getByText('Step 4 of 5')).toBeVisible();
    await page.getByRole('button', { name: /^Next/ }).click();

    // Step 5: confirm.
    await expect(page.getByText('Step 5 of 5')).toBeVisible();
    await page.getByRole('button', { name: /Issue command/ }).click();

    // POST went through, toast fires, dialog closes.
    await expect.poll(() => issuedCount).toBeGreaterThan(0);
    await expect(page.getByText('Command issued')).toBeVisible();

    // New row visible in the list.
    await expect(page.getByText('systemctl status nginx').first()).toBeVisible();
  });
});
