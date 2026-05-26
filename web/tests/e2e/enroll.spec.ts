import { test, expect, type Route } from '@playwright/test';

/**
 * Smoke test for the /enroll magic-link page.
 *
 * The page consumes two endpoints on mount: `/v1/dash/settings/groups`
 * (to populate the group dropdown) and `/v1/dash/enroll/links` (to list
 * active links). The real backend integration is covered by
 * `server/tests/test_dash_enroll_links.py`; here we only verify the page
 * renders, the form is visible, and an existing link surfaces in the table.
 */

test('enroll page renders form and active links when authed as admin', async ({ page }) => {
  await page.route('**/auth/me', (route: Route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        user_id: '11111111-1111-1111-1111-111111111111',
        user_email: 'admin@test.local',
        user_role: 'admin',
        authenticated: true,
      }),
    }),
  );

  await page.route('**/v1/dash/settings/groups', (route: Route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        groups: [
          {
            name: 'prod',
            description: 'Production fleet',
            host_count: 3,
            user_count: 2,
            auto_distribute_keys: true,
            created_at: '2026-05-26T00:00:00Z',
          },
          {
            name: 'family',
            description: null,
            host_count: 1,
            user_count: 1,
            auto_distribute_keys: true,
            created_at: '2026-05-26T00:00:00Z',
          },
        ],
      }),
    }),
  );

  await page.route('**/v1/dash/enroll/links', (route: Route) => {
    if (route.request().method() !== 'GET') {
      return route.fallback();
    }
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        links: [
          {
            token_jti: 'jti-existing-1',
            group_name: 'family',
            issued_by: 'admin@test.local',
            expires_at: new Date(Date.now() + 12 * 3_600_000).toISOString(),
            max_uses: 1,
            used_count: 0,
            created_at: '2026-05-26T00:00:00Z',
          },
        ],
      }),
    });
  });

  // baseURL ends in `/dash-next/`; use a relative path so the URL
  // constructor preserves the SPA base. See `playwright.config.ts`.
  await page.goto('enroll');

  // Form mounts
  await expect(page.getByTestId('enroll-page')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Enroll an agent' })).toBeVisible();
  await expect(page.getByTestId('enroll-form-card')).toBeVisible();
  // Restored to data-testid now that Button spreads `...rest`.
  await expect(page.getByTestId('enroll-submit')).toBeVisible();

  // Group dropdown is populated from the settings endpoint.
  const groupSelect = page.getByTestId('enroll-group');
  await expect(groupSelect).toBeVisible();
  await expect(groupSelect.locator('option', { hasText: 'prod' })).toHaveCount(1);
  await expect(groupSelect.locator('option', { hasText: 'family' })).toHaveCount(1);

  // Existing link renders in the table.
  await expect(page.getByTestId('enroll-link-row')).toHaveCount(1);
  await expect(page.getByText('admin@test.local')).toBeVisible();
  // Restored to data-testid now that Button spreads `...rest`.
  await expect(page.getByTestId('enroll-revoke-btn')).toBeVisible();
});
