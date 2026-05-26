import { test, expect, type Route } from '@playwright/test';

/**
 * Minimal Phase-4 smoke test for the Settings page.
 *
 * The SvelteKit app fetches the API directly on mount, so we intercept the
 * `/v1/dash/settings/*` and `/auth/me` calls with deterministic fixtures.
 * The real backend integration is covered by `server/tests/test_dash_settings.py`.
 */

test('settings page renders both tabs when authed as admin', async ({ page }) => {
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
            name: 'stage',
            description: null,
            host_count: 0,
            user_count: 0,
            auto_distribute_keys: true,
            created_at: '2026-05-26T00:00:00Z',
          },
        ],
      }),
    }),
  );

  await page.route('**/v1/dash/settings/users', (route: Route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        users: [
          {
            id: '22222222-2222-2222-2222-222222222222',
            email: 'admin@test.local',
            name: 'Admin',
            role: 'admin',
            groups: [],
            is_active: true,
            created_at: '2026-05-26T00:00:00Z',
            last_login_at: '2026-05-26T00:00:00Z',
          },
          {
            id: '33333333-3333-3333-3333-333333333333',
            email: 'viewer@test.local',
            name: null,
            role: 'viewer',
            groups: ['prod'],
            is_active: true,
            created_at: '2026-05-26T00:00:00Z',
            last_login_at: null,
          },
        ],
      }),
    }),
  );

  // baseURL ends in `/dash-next/`; use a relative path so the URL
  // constructor preserves the SPA base. See `playwright.config.ts`.
  await page.goto('settings');

  // Page mounts
  await expect(page.getByTestId('settings-page')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible();

  // Both tabs visible
  const groupsTab = page.getByTestId('tab-groups');
  const usersTab = page.getByTestId('tab-users');
  await expect(groupsTab).toBeVisible();
  await expect(usersTab).toBeVisible();

  // Default tab = groups, table shows seeded fixture rows. We scope to
  // the cell role so we don't collide with the group-membership pills
  // rendered for each user under the Users tab (also in the DOM).
  await expect(page.getByRole('cell', { name: 'prod', exact: true })).toBeVisible();
  await expect(page.getByText('Production fleet')).toBeVisible();
  // Restored after Button spreads `...rest` (was role-based as a
  // workaround for the v1.0.5 forwarding bug).
  await expect(page.getByTestId('new-group-btn')).toBeVisible();

  // Switch to Users tab
  await usersTab.click();
  await expect(page.getByText('admin@test.local')).toBeVisible();
  await expect(page.getByText('viewer@test.local')).toBeVisible();
  await expect(page.getByTestId('new-user-btn')).toBeVisible();
});
