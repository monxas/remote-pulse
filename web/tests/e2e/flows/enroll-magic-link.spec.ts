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
    // Default TTL is now 5 minutes; the test selects "30 min" via the
    // preset dropdown to mirror a realistic operator flow.
    const expiresAt = new Date(Date.now() + 30 * 60_000).toISOString();
    const issuedLink = {
      // New short-code fields (preferred surface).
      code: 'K7M-X3F',
      install_url: 'curl https://rp.example/install | sh -s -- --code=K7M-X3F',
      install_url_windows_short:
        "$env:RP_CODE='K7M-X3F'; iwr -useb https://rp.example/install.ps1 | iex",
      // Legacy fields kept for back-compat (still emitted by server).
      url: 'https://rp.example/install?token=eyJfake.jwt.payload',
      install_url_windows: 'https://rp.example/install.ps1?token=eyJfake.jwt.payload',
      token: 'eyJfake.jwt.payload',
      token_jti: 'jti-new-1',
      group_name: 'family',
      issued_by: 'admin@test.local',
      expires_at: expiresAt,
      expires_in_seconds: 1800,
      expires_in_hours: 0,
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
            code: issuedLink.code,
            install_url_short: issuedLink.install_url,
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

    // Fill form: pick `family`, choose the "30 min" preset, add a label.
    await page.getByTestId('enroll-group').selectOption('family');
    // TTL is now a <select> of presets (5/30/120/1440 min). Pick 30 min.
    await page.getByTestId('enroll-ttl').selectOption('30');
    await page.getByTestId('enroll-max-uses').fill('1');
    await page.getByTestId('enroll-label').fill('Mac mini test');

    await page.getByRole('button', { name: /Generate code/i }).click();

    // POST fired, result card shows the hero short code + the install command.
    await expect.poll(() => createCount).toBe(1);
    await expect(page.getByTestId('enroll-result-card')).toBeVisible();
    await expect(page.getByTestId('enroll-code-hero')).toContainText(issuedLink.code);
    await expect(page.getByTestId('enroll-install-cmd')).toContainText(
      '--code=K7M-X3F',
    );
    await expect(page.getByTestId('enroll-copy-install')).toBeVisible();
    // Live countdown should render in m / m:ss form (e.g. "29m 59s" or "29m").
    await expect(page.getByTestId('enroll-countdown')).toContainText(/\d+m/);

    // The active-links table now has exactly one row with the code surfaced.
    await expect(page.getByTestId('enroll-link-row')).toHaveCount(1);
    await expect(page.getByTestId('enroll-row-code')).toContainText('K7M-X3F');
    await expect(page.getByTestId('enroll-link-row').getByText('family')).toBeVisible();

    // Legacy JWT URL is still reachable inside the collapsible "Advanced" section.
    await page.getByTestId('enroll-legacy-details').click();
    await expect(page.getByTestId('enroll-url')).toContainText(issuedLink.url);

    // Revoke it — the page calls `window.confirm()` which we auto-accept.
    await page.getByTestId('enroll-revoke-btn').click();
    await expect.poll(() => revokeCount).toBe(1);
    await expect(page.getByTestId('enroll-link-row')).toHaveCount(0);
    await expect(
      page.getByText('No active codes. Generate one above to enroll a new agent.'),
    ).toBeVisible();
  });
});
