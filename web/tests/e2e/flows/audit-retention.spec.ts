import { test, expect, type Route } from '@playwright/test';
import { mockAdminAuth, mockSseSilent } from '../helpers/auth';

/**
 * Flow — admin lands on Settings → Retention, sees the current policy,
 * edits the day count, saves it, then triggers a manual purge from the
 * confirm modal.
 *
 * Like the webhooks flow this is mock-only — every retention endpoint
 * is intercepted, no backend required.
 */

test.describe('flow: audit retention policy', () => {
  test('admin updates retention days and triggers a manual purge', async ({ page }) => {
    await mockAdminAuth(page);
    await mockSseSilent(page);

    // Mutable in-memory config so the GET after the PATCH reflects
    // the new state — matches the production cache-invalidation path.
    let current = {
      retention_days: 90,
      enabled: true,
      last_purge_at: '2026-05-27T10:00:00Z',
      last_purge_count: 42,
      updated_by: 'system',
      updated_at: '2026-05-27T10:00:00Z',
      min_days: 7,
      max_days: 3650,
    };
    let patchCount = 0;
    let purgeCount = 0;

    await page.route('**/v1/dash/settings/retention', (route: Route) => {
      const req = route.request();
      if (req.method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(current),
        });
      }
      if (req.method() === 'PATCH') {
        patchCount += 1;
        const body = JSON.parse(req.postData() ?? '{}') as Record<string, unknown>;
        current = {
          ...current,
          retention_days:
            typeof body.retention_days === 'number' ? body.retention_days : current.retention_days,
          enabled: typeof body.enabled === 'boolean' ? body.enabled : current.enabled,
          updated_by: 'admin@test.local',
          updated_at: new Date().toISOString(),
        };
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(current),
        });
      }
      return route.fallback();
    });

    await page.route('**/v1/dash/settings/retention/purge-now', (route: Route) => {
      if (route.request().method() !== 'POST') return route.fallback();
      purgeCount += 1;
      current = {
        ...current,
        last_purge_at: new Date().toISOString(),
        last_purge_count: 7,
      };
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          deleted: 7,
          retention_days: current.retention_days,
          enabled: current.enabled,
        }),
      });
    });

    await page.goto('settings');
    await expect(page.getByTestId('settings-page')).toBeVisible();

    // Switch to the new Retention tab.
    await page.getByTestId('tab-retention').click();
    await expect(page.getByTestId('retention-card')).toBeVisible();

    // Current value should reflect the mock (90).
    await expect(page.getByTestId('retention-current-days')).toHaveText('90');

    // Edit the number input to 60 and save.
    const daysInput = page.getByTestId('retention-days-input');
    await daysInput.fill('60');
    await page.getByTestId('retention-save').click();

    await expect.poll(() => patchCount).toBe(1);
    // After the cache invalidates the status line should update.
    await expect(page.getByTestId('retention-current-days')).toHaveText('60');

    // Trigger manual purge: confirm modal then confirm.
    await page.getByTestId('retention-purge-now').click();
    await page.getByTestId('retention-purge-confirm').click();

    await expect.poll(() => purgeCount).toBe(1);

    // After the purge the last_purge_count surface should reflect 7.
    await expect(page.getByTestId('retention-last-purge')).toContainText('7 event');
  });

  test('non-admin sees the friendly placeholder, not the controls', async ({ page }) => {
    await mockAdminAuth(page, { user_role: 'viewer' });
    await mockSseSilent(page);

    await page.goto('settings');
    await page.getByTestId('tab-retention').click();
    await expect(page.getByTestId('retention-non-admin')).toBeVisible();
    await expect(page.getByTestId('retention-card')).toHaveCount(0);
  });
});
