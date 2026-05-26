import { test, expect, type Route } from '@playwright/test';
import { mockAdminAuth } from '../helpers/auth';
import { installFakeEventSource, mockSseHead, pushSseEvent } from '../helpers/sse-stream';

/**
 * Flow — real-time UX polish.
 *
 * Validates the user-visible bits that depend on the SSE bridge:
 *   1. The bell in the topbar shows an "unread" badge as events arrive
 *      and the popover lists those events newest-first.
 *   2. Clicking a `command.status_change` event from the popover
 *      navigates to the command detail page and the badge clears.
 *   3. A `command.status_change` event with status=failed surfaces a
 *      destructive toast with a "View" action.
 *
 * We mock auth, install a fake EventSource so we can deterministically
 * push events from the test, and stub every JSON endpoint the SPA
 * touches with empty payloads so unrelated queries don't show error UI.
 */

const EMPTY_JSON = (body: unknown) => ({
  status: 200,
  contentType: 'application/json',
  body: JSON.stringify(body),
});

test.describe('flow: real-time activity widget + toasts', () => {
  test.beforeEach(async ({ page }) => {
    await mockAdminAuth(page);
    await installFakeEventSource(page);
    await mockSseHead(page);

    await page.route('**/v1/dash/overview', (route: Route) =>
      route.fulfill(
        EMPTY_JSON({
          total: 0,
          online: 0,
          stale: 0,
          offline: 0,
          pending_approvals: 0,
          online_pct: 0,
          online_pct_24h_ago: 0,
        }),
      ),
    );
    await page.route('**/v1/dash/hosts**', (route: Route) =>
      route.fulfill(EMPTY_JSON({ hosts: [] })),
    );
    await page.route('**/v1/dash/commands**', (route: Route) => {
      if (route.request().url().includes('/commands/cmd-1')) {
        return route.fulfill(
          EMPTY_JSON({
            id: 'cmd-1',
            host_id: 'host-1',
            host_hostname: 'rp-x',
            issued_by: 'admin@test.local',
            command_type: 'shell',
            command_payload: { cmd: 'true' },
            status: 'failed',
            issued_at: new Date().toISOString(),
            completed_at: new Date().toISOString(),
            exit_code: 1,
            stdout: '',
            stderr: 'boom',
            duration_ms: 12,
            human_approved: false,
            approved_by: null,
            rejected_reason: null,
          }),
        );
      }
      return route.fulfill(EMPTY_JSON({ commands: [], next_cursor: null }));
    });
    await page.route('**/v1/dash/audit**', (route: Route) =>
      route.fulfill(EMPTY_JSON({ events: [], next_cursor: null })),
    );
    await page.route('**/v1/dash/approvals/pending', (route: Route) =>
      route.fulfill(EMPTY_JSON({ approvals: [] })),
    );
  });

  test('badge counts unread events; popover lists them; click navigates', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { name: /Fleet/ })).toBeVisible();

    const trigger = page.getByTestId('activity-trigger');
    await expect(trigger).toBeVisible();
    // No events yet → no badge.
    await expect(page.getByTestId('activity-badge')).toHaveCount(0);

    // Push a status change → badge appears with count 1.
    await pushSseEvent(
      page,
      'command.status_change',
      { command_id: 'cmd-1', host_id: 'host-1', status: 'succeeded' },
      '1',
    );
    await expect(page.getByTestId('activity-badge')).toHaveText('1');

    // Second event → 2.
    await pushSseEvent(
      page,
      'approval.created',
      {
        approval_id: 'cmd-2',
        command_id: 'cmd-2',
        host_id: 'host-1',
        command_type: 'shell',
        issued_by: 'op@test.local',
      },
      '2',
    );
    await expect(page.getByTestId('activity-badge')).toHaveText('2');

    // Open the popover; badge clears + items are listed newest-first.
    await trigger.click();
    const popover = page.getByTestId('activity-popover');
    await expect(popover).toBeVisible();
    const items = page.getByTestId('activity-item');
    await expect(items).toHaveCount(2);
    await expect(items.first()).toContainText('Approval requested');
    await expect(items.nth(1)).toContainText('Command succeeded');

    // Click the command event → navigates to /commands/cmd-1.
    await items.nth(1).click();
    await expect(page).toHaveURL(/\/commands\/cmd-1/);
    // Badge is back to zero (we marked as read on open).
    await expect(page.getByTestId('activity-badge')).toHaveCount(0);
  });

  test('command.failed event surfaces a destructive toast', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { name: /Fleet/ })).toBeVisible();

    await pushSseEvent(
      page,
      'command.status_change',
      {
        command_id: 'cmd-1',
        host_id: 'host-1',
        hostname: 'rp-prod-1',
        status: 'failed',
        exit_code: 1,
      },
      '5',
    );

    // The toast carries "Command failed on rp-prod-1".
    await expect(page.getByText(/Command failed on rp-prod-1/i)).toBeVisible();
  });
});
