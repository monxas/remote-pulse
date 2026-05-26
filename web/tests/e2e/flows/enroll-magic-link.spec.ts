import { test, expect, type Route } from '@playwright/test';
import { mockAdminAuth, mockSseSilent } from '../helpers/auth';

/**
 * Flow 4 — Issue + revoke a magic-link enrollment URL.
 *
 * Admin fills the form, hits "Generate magic-link", the server returns
 * the issued JWT + URL, the result card surfaces with copy buttons, and
 * the new row appears in the "Active magic-links" table. Then we revoke
 * it: the `window.confirm` prompt is auto-accepted, the DELETE call
 * fires, and the row disappears.
 */

test.describe('flow: issue + revoke enroll magic-link', () => {
  test('admin can generate a magic-link, see it in the active table, then revoke it', async ({
    page,
  }) => {
    await mockAdminAuth(page);
    await mockSseSilent(page);

    // Auto-accept the `window.confirm` prompt fired by `confirmRevoke`.
    page.on('dialog', (dialog) => void dialog.accept());

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

    const issuedAt = '2026-05-26T00:00:00Z';
    const expiresAt = new Date(Date.now() + 6 * 3_600_000).toISOString();
    const issuedLink = {
      url: 'https://rp.example/install/abc',
      install_url_windows: 'https://rp.example/install/abc.ps1',
      token: 'eyJfake.jwt.payload',
      token_jti: 'jti-new-1',
      group_name: 'family',
      issued_by: 'admin@test.local',
      expires_at: expiresAt,
      expires_in_hours: 6,
      max_uses: 1,
      used_count: 0,
      label: 'Mac mini test',
    };

    let createCount = 0;
    let revokeCount = 0;
    // Track which links should be returned by the GET — starts empty,
    // gains the issued row after POST, empties again after DELETE.
    let activeLinks: Array<Record<string, unknown>> = [];

    await page.route('**/v1/dash/enroll/links', (route: Route) => {
      const req = route.request();
      if (req.method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ links: activeLinks }),
        });
      }
      if (req.method() === 'POST') {
        createCount += 1;
        activeLinks = [
          {
            token_jti: issuedLink.token_jti,
            group_name: issuedLink.group_name,
            issued_by: issuedLink.issued_by,
            expires_at: issuedLink.expires_at,
            max_uses: issuedLink.max_uses,
            used_count: issuedLink.used_count,
            created_at: issuedAt,
          },
        ];
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(issuedLink),
        });
      }
      return route.fallback();
    });

    await page.route('**/v1/dash/enroll/links/jti-new-1', (route: Route) => {
      if (route.request().method() !== 'DELETE') return route.fallback();
      revokeCount += 1;
      activeLinks = [];
      return route.fulfill({ status: 204, body: '' });
    });

    await page.goto('enroll');
    await expect(page.getByTestId('enroll-page')).toBeVisible();

    // Fill form: pick `family`, leave TTL/max-uses defaults, add a label.
    await page.getByTestId('enroll-group').selectOption('family');
    await page.getByTestId('enroll-ttl').fill('6');
    await page.getByTestId('enroll-max-uses').fill('1');
    await page.getByTestId('enroll-label').fill('Mac mini test');

    await page.getByRole('button', { name: /Generate magic-link/i }).click();

    // POST fired, result card shows the URL + a Copy button.
    await expect.poll(() => createCount).toBe(1);
    await expect(page.getByTestId('enroll-result-card')).toBeVisible();
    await expect(page.getByTestId('enroll-url')).toContainText(issuedLink.url);
    // <Button> drops `data-testid`, so we identify Copy by visible text.
    // (There may be more than one Copy button once the Windows details
    // block is expanded, so use `.first()`.)
    await expect(page.getByRole('button', { name: 'Copy' }).first()).toBeVisible();

    // The active-links table now has exactly one row.
    await expect(page.getByTestId('enroll-link-row')).toHaveCount(1);
    await expect(page.getByTestId('enroll-link-row').getByText('family')).toBeVisible();

    // Revoke it — the page calls `window.confirm()` which we auto-accept.
    await page.getByRole('button', { name: 'Revoke' }).click();
    await expect.poll(() => revokeCount).toBe(1);
    await expect(page.getByTestId('enroll-link-row')).toHaveCount(0);
    await expect(
      page.getByText('No active magic-links. Generate one above to enroll a new agent.'),
    ).toBeVisible();
  });
});
