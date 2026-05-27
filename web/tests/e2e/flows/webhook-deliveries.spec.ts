import { test, expect, type Route } from '@playwright/test';
import { mockAdminAuth, mockSseSilent } from '../helpers/auth';

/**
 * Flow — admin opens the deliveries log for a webhook, sees recent
 * attempts with status badges, retries a failed delivery, and resets
 * failure counters on an auto-disabled hook.
 *
 * Entirely mock-driven: we intercept the webhook list + deliveries
 * endpoints and the retry/reset-failures calls so we can assert exactly
 * what the page would POST against a real server.
 */

const WEBHOOK_ID = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';

test.describe('flow: webhook deliveries log', () => {
  test('renders 5 deliveries with status badges and retries a failed row', async ({ page }) => {
    await mockAdminAuth(page);
    await mockSseSilent(page);

    let retryCount = 0;
    let lastRetryDeliveryId = '';

    // Webhook list: needed for the page header (name/url come from the
    // cached list).
    await page.route('**/v1/dash/webhooks', (route: Route) => {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          webhooks: [
            {
              id: WEBHOOK_ID,
              name: 'n8n bridge',
              url: 'https://n8n.example/webhook/rp',
              event_filter: ['*'],
              group_filter: null,
              enabled: true,
              created_by: 'admin@test.local',
              created_at: '2026-05-27T00:00:00Z',
              last_fired_at: '2026-05-27T00:01:00Z',
              last_status_code: 502,
              last_error: 'HTTP 502',
              failure_count: 3,
            },
          ],
        }),
      });
    });

    // Deliveries: 5 entries, mix of 200 / 404 / 502 / timeout / 200.
    const deliveries = [
      mkDelivery('d-200a', 'command.issued', 200, true, null, 1),
      mkDelivery('d-404', 'host.heartbeat', 404, false, 'HTTP 404', 4),
      mkDelivery('d-502', 'command.issued', 502, false, 'HTTP 502', 4),
      mkDelivery('d-timeout', 'command.issued', null, false, 'ConnectTimeout: timed out', 4),
      mkDelivery('d-200b', 'webhook.test', 200, true, null, 1),
    ];

    await page.route(`**/v1/dash/webhooks/${WEBHOOK_ID}/deliveries`, (route: Route) => {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          webhook_id: WEBHOOK_ID,
          deliveries,
          max_history: 20,
        }),
      });
    });

    await page.route(
      new RegExp(`/v1/dash/webhooks/${WEBHOOK_ID}/deliveries/[^/]+/retry$`),
      (route: Route) => {
        if (route.request().method() !== 'POST') return route.fallback();
        retryCount += 1;
        const url = route.request().url();
        lastRetryDeliveryId = url.split('/').slice(-2, -1)[0] ?? '';
        return route.fulfill({
          status: 202,
          contentType: 'application/json',
          body: JSON.stringify({
            status: 'queued',
            webhook_id: WEBHOOK_ID,
            retry_of: lastRetryDeliveryId,
          }),
        });
      },
    );

    await page.goto(`webhooks/${WEBHOOK_ID}/deliveries`);
    await expect(page.getByTestId('webhook-deliveries-page')).toBeVisible();

    // Header reflects the webhook from the list cache.
    await expect(page.getByRole('heading', { name: /n8n bridge/i })).toBeVisible();

    // All 5 rows render.
    await expect(page.getByTestId('delivery-row')).toHaveCount(5);

    // Status badges — at least one success and one danger should appear.
    const badges = page.getByTestId('delivery-status-badge');
    await expect(badges.filter({ hasText: '200' }).first()).toBeVisible();
    await expect(badges.filter({ hasText: '404' })).toBeVisible();
    await expect(badges.filter({ hasText: '502' })).toBeVisible();
    // Timeout row has no status_code → shows "timeout" label.
    await expect(badges.filter({ hasText: /timeout/i })).toBeVisible();

    // Retry buttons only appear on failed rows. We seeded 3 failed
    // entries (404, 502, timeout) so we expect exactly 3 retry buttons.
    const retryButtons = page.getByTestId('delivery-retry-btn');
    await expect(retryButtons).toHaveCount(3);

    // Click retry on the 502 row specifically.
    const row502 = page.locator('[data-testid="delivery-row"][data-delivery-id="d-502"]');
    await row502.getByTestId('delivery-retry-btn').click();

    await expect.poll(() => retryCount).toBe(1);
    expect(lastRetryDeliveryId).toBe('d-502');
  });

  test('reset-failures from /webhooks re-enables an auto-disabled hook', async ({ page }) => {
    await mockAdminAuth(page);
    await mockSseSilent(page);

    // Hook starts auto-disabled (failure_count >= 10 + enabled false).
    let row: Record<string, unknown> = {
      id: WEBHOOK_ID,
      name: 'broken bridge',
      url: 'https://broken.example/webhook',
      event_filter: ['*'],
      group_filter: null,
      enabled: false,
      created_by: 'admin@test.local',
      created_at: '2026-05-27T00:00:00Z',
      last_fired_at: '2026-05-27T00:01:00Z',
      last_status_code: 500,
      last_error: 'HTTP 500',
      failure_count: 10,
    };

    let resetCount = 0;

    await page.route('**/v1/dash/webhooks', (route: Route) => {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ webhooks: [row] }),
      });
    });

    await page.route(`**/v1/dash/webhooks/${WEBHOOK_ID}/reset-failures`, (route: Route) => {
      if (route.request().method() !== 'POST') return route.fallback();
      resetCount += 1;
      row = { ...row, enabled: true, failure_count: 0, last_error: null };
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(row),
      });
    });

    // Auto-accept the confirm() dialog the page raises.
    page.on('dialog', (d) => {
      void d.accept();
    });

    await page.goto('webhooks');
    await expect(page.getByTestId('webhooks-page')).toBeVisible();

    // Auto-disabled badge visible.
    await expect(page.getByTestId('webhook-autodisabled-badge')).toBeVisible();
    await expect(page.getByTestId('webhook-autodisabled-badge')).toContainText(/auto-disabled/i);

    // Click "Reset failures".
    await page.getByTestId('webhook-reset-failures-btn').click();
    await expect.poll(() => resetCount).toBe(1);

    // Toast confirming re-enable.
    await expect(page.getByText(/Failures reset/i)).toBeVisible();
  });
});

function mkDelivery(
  id: string,
  event: string,
  status: number | null,
  success: boolean,
  error: string | null,
  attempt: number,
): Record<string, unknown> {
  return {
    delivery_id: id,
    event,
    timestamp: new Date(Date.now() - 60_000).toISOString(),
    status_code: status,
    error,
    attempt,
    success,
  };
}
