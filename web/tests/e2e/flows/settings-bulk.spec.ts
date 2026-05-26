import { test, expect, type Route } from '@playwright/test';
import { mockAdminAuth, mockSseSilent } from '../helpers/auth';

/**
 * Flow — bulk operations on the Settings page.
 *
 * Exercises the follow-up scope from v1.0.9 (#37): multi-select + bulk
 * actions in the Users and Groups tabs.
 *
 * Scenarios:
 *   1. Users tab: select 3 → change role → assert 3 PATCH fan-out.
 *   2. Users tab: select 3 including the signed-in admin → delete →
 *      modal refuses, surfaces the self-warning, no DELETE fires.
 *   3. Groups tab: select 3 (one with hosts) → bulk delete button is
 *      disabled and the bar shows the blocked-groups hint.
 */

const ADMIN_ID = '11111111-1111-1111-1111-111111111111';
const ADMIN_EMAIL = 'admin@test.local';

interface UserRow {
  id: string;
  email: string;
  name: string | null;
  role: 'admin' | 'operator' | 'viewer';
  groups: string[];
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

function mkUser(over: Partial<UserRow> & { id: string; email: string }): UserRow {
  return {
    name: null,
    role: 'viewer',
    groups: ['prod'],
    is_active: true,
    created_at: new Date().toISOString(),
    last_login_at: null,
    ...over,
  };
}

test.describe('flow: settings bulk operations', () => {
  test('Users: select 3 and bulk change role fires 3 PATCHes', async ({ page }) => {
    await mockAdminAuth(page, { user_id: ADMIN_ID, user_email: ADMIN_EMAIL });
    await mockSseSilent(page);

    const users: UserRow[] = [
      mkUser({ id: ADMIN_ID, email: ADMIN_EMAIL, role: 'admin' }),
      mkUser({ id: 'u2', email: 'op1@test.local', role: 'operator' }),
      mkUser({ id: 'u3', email: 'op2@test.local', role: 'operator' }),
      mkUser({ id: 'u4', email: 'op3@test.local', role: 'operator' }),
    ];

    const patched: { id: string; body: unknown }[] = [];

    await page.route('**/v1/dash/settings/groups', (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          groups: [
            { name: 'prod', description: 'prod', host_count: 0, user_count: 4 },
            { name: 'family', description: null, host_count: 0, user_count: 0 },
          ],
        }),
      }),
    );

    await page.route('**/v1/dash/settings/users', (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ users }),
      }),
    );

    await page.route(/\/v1\/dash\/settings\/users\/[^/]+$/, (route: Route) => {
      const req = route.request();
      const match = req.url().match(/\/users\/([^/?]+)/);
      const id = match?.[1] ?? '';
      if (req.method() === 'PATCH') {
        patched.push({ id, body: req.postDataJSON() });
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ ...users.find((u) => u.id === id), role: 'viewer' }),
        });
      }
      return route.fallback();
    });

    await page.goto('settings');
    await page.getByTestId('tab-users').click();
    await expect(page.getByTestId('users-table')).toBeVisible();

    // Select the 3 operators (NOT the admin self).
    await page.getByTestId('select-user-op1@test.local').click();
    await page.getByTestId('select-user-op2@test.local').click();
    await page.getByTestId('select-user-op3@test.local').click();

    const bar = page.getByTestId('bulk-user-action-bar');
    await expect(bar).toBeVisible();
    await expect(bar).toContainText('3');

    // Open change-role modal.
    await page.getByTestId('bulk-change-role').click();
    await expect(page.getByRole('dialog')).toBeVisible();
    await page.getByTestId('bulk-role-select').selectOption('viewer');

    await page.getByTestId('bulk-user-submit').click();

    // Wait for all 3 PATCHes to fan out.
    await expect.poll(() => patched.length).toBe(3);
    expect(new Set(patched.map((p) => p.id))).toEqual(new Set(['u2', 'u3', 'u4']));
    for (const p of patched) {
      expect((p.body as { role?: string }).role).toBe('viewer');
    }

    // Success toast surfaces with the count.
    await expect(page.getByText(/3 roles updated/)).toBeVisible();
  });

  test('Users: bulk delete with self in selection refuses without firing requests', async ({
    page,
  }) => {
    await mockAdminAuth(page, { user_id: ADMIN_ID, user_email: ADMIN_EMAIL });
    await mockSseSilent(page);

    const users: UserRow[] = [
      mkUser({ id: ADMIN_ID, email: ADMIN_EMAIL, role: 'admin' }),
      mkUser({ id: 'u2', email: 'op@test.local', role: 'operator' }),
      mkUser({ id: 'u3', email: 'viewer@test.local', role: 'viewer' }),
    ];

    let deleteCount = 0;

    await page.route('**/v1/dash/settings/groups', (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          groups: [{ name: 'prod', description: null, host_count: 0, user_count: 3 }],
        }),
      }),
    );

    await page.route('**/v1/dash/settings/users', (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ users }),
      }),
    );

    await page.route(/\/v1\/dash\/settings\/users\/[^/]+$/, (route: Route) => {
      if (route.request().method() === 'DELETE') {
        deleteCount += 1;
        return route.fulfill({ status: 204, body: '' });
      }
      return route.fallback();
    });

    await page.goto('settings');
    await page.getByTestId('tab-users').click();

    // Toggle "select all visible" — includes the signed-in admin.
    await page.getByTestId('select-all-users').click();
    await expect(page.getByTestId('bulk-user-action-bar')).toContainText('3');

    await page.getByTestId('bulk-delete-users').click();

    // Modal opens with the self-warning banner; submit must be disabled.
    await expect(page.getByTestId('bulk-delete-self-warning')).toBeVisible();
    await expect(page.getByTestId('bulk-user-submit')).toBeDisabled();

    // No DELETE should have fired.
    expect(deleteCount).toBe(0);
  });

  test('Groups: bulk delete disabled when any selected group has hosts', async ({ page }) => {
    await mockAdminAuth(page);
    await mockSseSilent(page);

    await page.route('**/v1/dash/settings/groups', (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          groups: [
            { name: 'prod', description: null, host_count: 2, user_count: 1 },
            { name: 'family', description: null, host_count: 0, user_count: 0 },
            { name: 'lab', description: null, host_count: 0, user_count: 0 },
          ],
        }),
      }),
    );
    await page.route('**/v1/dash/settings/users', (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ users: [] }),
      }),
    );

    let deleteCount = 0;
    await page.route(/\/v1\/dash\/settings\/groups\/[^/]+$/, (route: Route) => {
      if (route.request().method() === 'DELETE') {
        deleteCount += 1;
        return route.fulfill({ status: 204, body: '' });
      }
      return route.fallback();
    });

    await page.goto('settings');
    await expect(page.getByTestId('groups-table')).toBeVisible();

    // Select all three — one has 2 hosts so the bar's button must be disabled.
    await page.getByTestId('select-all-groups').click();
    const bar = page.getByTestId('bulk-group-action-bar');
    await expect(bar).toBeVisible();
    await expect(page.getByTestId('bulk-group-blocked')).toContainText(/1 group/);
    await expect(page.getByTestId('bulk-delete-groups')).toBeDisabled();

    // De-select the blocked one — now the action enables.
    await page.getByTestId('select-group-prod').click();
    await expect(page.getByTestId('bulk-delete-groups')).toBeEnabled();

    // Open dialog + confirm with the exact phrase.
    await page.getByTestId('bulk-delete-groups').click();
    await page.getByTestId('bulk-group-delete-confirm').fill('DELETE');
    await page.getByTestId('bulk-group-delete-submit').click();

    await expect.poll(() => deleteCount).toBe(2);
    await expect(page.getByText(/2 groups deleted/)).toBeVisible();
  });
});
