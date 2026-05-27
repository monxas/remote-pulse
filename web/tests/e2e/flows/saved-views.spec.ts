import { test, expect, type Route } from '@playwright/test';
import { mockAdminAuth, mockSseSilent } from '../helpers/auth';

/**
 * Flow — Saved views (feat/saved-views).
 *
 * Covers the SavedViewsSwitcher on /audit:
 *  - Factory pill "Last 7 days" applies range=7d to the URL on click.
 *  - Apply a filter manually → switcher shows "Modified".
 *  - "Save current as view…" persists a named preset to localStorage.
 *  - Reload → the saved view survives + re-applies on click.
 *  - "Manage views…" lets the user delete the custom view.
 */

test.describe('flow: saved views', () => {
  test.beforeEach(async ({ page }) => {
    await mockAdminAuth(page);
    await mockSseSilent(page);

    // Bare-minimum audit + overview responses — content doesn't matter
    // for this flow, only the URL plumbing and DOM does.
    await page.route('**/v1/dash/audit**', (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          events: [],
          next_cursor: null,
          total: 0,
          limit: 100,
          offset: 0,
          has_more: false,
        }),
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

    // Reset localStorage when the first page-context loads — Playwright
    // re-runs `addInitScript` on every navigation (including reloads),
    // which would wipe a view we just persisted. We gate on a sentinel
    // so the reset only fires once per test.
    await page.addInitScript(() => {
      try {
        if (!window.sessionStorage.getItem('__sv_test_init')) {
          window.localStorage.removeItem('rp:saved-views:audit');
          window.sessionStorage.setItem('__sv_test_init', '1');
        }
      } catch {
        /* SecurityError in some test contexts */
      }
    });
  });

  test('factory "Last 7 days" pill applies range=7d', async ({ page }) => {
    await page.goto('audit');
    await expect(page.getByRole('heading', { name: 'Audit log' })).toBeVisible();

    await page.getByTestId('saved-views-factory-factory:last-7-days').click();
    await expect.poll(() => new URL(page.url()).searchParams.get('range')).toBe('7d');
  });

  test('save current filters as a named view and re-apply after reload', async ({ page }) => {
    await page.goto('audit');
    await expect(page.getByRole('heading', { name: 'Audit log' })).toBeVisible();

    // Apply a filter manually so the switcher transitions to "Modified".
    await page.getByTestId('audit-action-prefix-filter').fill('host.');
    await expect
      .poll(() => new URL(page.url()).searchParams.get('action_prefix'))
      .toBe('host.');

    // Open the switcher dropdown and start a "Save as".
    await page.getByTestId('saved-views-trigger').click();
    await page.getByTestId('saved-views-save').click();

    await page.getByTestId('saved-views-save-name').fill('My host events');
    await page.getByTestId('saved-views-save-submit').click();

    // The view persists to localStorage scoped to audit.
    const stored = await page.evaluate(() => localStorage.getItem('rp:saved-views:audit'));
    expect(stored).toBeTruthy();
    expect(stored).toContain('My host events');

    // Reload the page — the saved view must survive.
    await page.reload();
    await expect(page.getByRole('heading', { name: 'Audit log' })).toBeVisible();

    // Drop the manual filter so we're back at "Default view" first.
    await page.getByTestId('saved-views-default').click();
    await expect.poll(() => new URL(page.url()).searchParams.get('action_prefix')).toBeNull();

    // Open the dropdown — our saved item should be there and apply on click.
    await page.getByTestId('saved-views-trigger').click();
    const item = page.getByRole('menuitem', { name: 'My host events' });
    await expect(item).toBeVisible();
    await item.click();

    await expect
      .poll(() => new URL(page.url()).searchParams.get('action_prefix'))
      .toBe('host.');
  });

  test('delete a custom view from the manage modal', async ({ page }) => {
    await page.goto('audit');
    await expect(page.getByRole('heading', { name: 'Audit log' })).toBeVisible();

    // Seed a view by filling + saving (avoid relying on localStorage
    // pre-injection so the test exercises the real save path).
    await page.getByTestId('audit-action-prefix-filter').fill('settings.');
    await expect
      .poll(() => new URL(page.url()).searchParams.get('action_prefix'))
      .toBe('settings.');
    await page.getByTestId('saved-views-trigger').click();
    await page.getByTestId('saved-views-save').click();
    await page.getByTestId('saved-views-save-name').fill('Settings only');
    await page.getByTestId('saved-views-save-submit').click();

    // Open Manage modal and delete it.
    await page.getByTestId('saved-views-trigger').click();
    await page.getByTestId('saved-views-manage').click();

    const rows = page.locator('[data-testid^="saved-views-manage-row-"]');
    await expect(rows).toHaveCount(1);

    // Click the trash button on the row.
    await page
      .locator('[data-testid^="saved-views-delete-"]')
      .first()
      .click();
    await expect(rows).toHaveCount(0);

    // localStorage should now hold an empty array.
    const stored = await page.evaluate(() => localStorage.getItem('rp:saved-views:audit'));
    expect(stored).toBe('[]');
  });
});
