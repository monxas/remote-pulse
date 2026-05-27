import { test, expect, type Route } from '@playwright/test';
import { mockAdminAuth, mockSseSilent } from '../helpers/auth';

/**
 * Flow — admin creates a webhook, sees the secret revealed once, the
 * row appears in the table, and the synthetic "Test" endpoint fires.
 *
 * The whole flow is mock-only — no backend required. We intercept every
 * /v1/dash/webhooks call and drive the page state from the test.
 */

test.describe('flow: webhooks page', () => {
  test('admin creates a webhook, secret is shown once, test fire confirms', async ({ page }) => {
    await mockAdminAuth(page);
    await mockSseSilent(page);

    // Mutable "DB" the route handlers read/write. Starts empty so the
    // empty-state copy renders first.
    let rows: Array<Record<string, unknown>> = [];
    let createCount = 0;
    let testCount = 0;
    const createdSecret = 'a'.repeat(64);

    await page.route('**/v1/dash/webhooks', (route: Route) => {
      const req = route.request();
      if (req.method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ webhooks: rows }),
        });
      }
      if (req.method() === 'POST') {
        createCount += 1;
        const body = JSON.parse(req.postData() ?? '{}') as Record<string, unknown>;
        const created = {
          id: '11111111-2222-3333-4444-555555555555',
          name: body.name,
          url: body.url,
          event_filter: body.event_filter,
          group_filter: body.group_filter ?? null,
          enabled: true,
          created_by: 'admin@test.local',
          created_at: '2026-05-27T00:00:00Z',
          last_fired_at: null,
          last_status_code: null,
          last_error: null,
          failure_count: 0,
        };
        rows = [created];
        return route.fulfill({
          status: 201,
          contentType: 'application/json',
          body: JSON.stringify({ ...created, secret: createdSecret }),
        });
      }
      return route.fallback();
    });

    await page.route(
      '**/v1/dash/webhooks/11111111-2222-3333-4444-555555555555/test',
      (route: Route) => {
        if (route.request().method() !== 'POST') return route.fallback();
        testCount += 1;
        return route.fulfill({
          status: 202,
          contentType: 'application/json',
          body: JSON.stringify({ status: 'queued' }),
        });
      },
    );

    await page.goto('webhooks');
    await expect(page.getByTestId('webhooks-page')).toBeVisible();

    // Empty state copy shows.
    await expect(page.getByText(/No webhooks yet/i)).toBeVisible();

    // Open the create modal.
    await page.getByTestId('webhooks-new-btn').click();
    await page.getByTestId('wh-name').fill('n8n bridge');
    await page.getByTestId('wh-url').fill('https://n8n.example/webhook/rp');
    await page.getByTestId('wh-create-submit').click();

    // POST fired, secret reveal dialog visible, secret matches.
    await expect.poll(() => createCount).toBe(1);
    await expect(page.getByTestId('wh-revealed-secret')).toContainText(createdSecret);
    await expect(page.getByTestId('wh-revealed-name')).toContainText('n8n bridge');

    // Dismiss the secret dialog.
    await page.getByRole('button', { name: /I have saved the secret/i }).click();

    // The row now appears in the table.
    await expect(page.getByTestId('webhook-row')).toHaveCount(1);
    await expect(page.getByTestId('webhook-row')).toContainText('n8n bridge');
    await expect(page.getByTestId('webhook-row')).toContainText('https://n8n.example/webhook/rp');

    // Fire the test button.
    await page.getByTestId('webhook-test-btn').click();
    await expect.poll(() => testCount).toBe(1);
    await expect(page.getByText(/Test event queued/i)).toBeVisible();
  });
});
