import { test, expect, type Route } from '@playwright/test';
import { mockAdminAuth, mockSseSilent } from '../helpers/auth';

/**
 * Flow — Audit filters + export (feat/audit-filters-export).
 *
 * Covers:
 * - URL state sync: typing into the actor filter pushes ``?actor=`` into
 *   the URL and re-issues the request to ``/v1/dash/audit`` with the
 *   filter applied.
 * - Result count: the "Showing N of M events" line reflects the server's
 *   ``total`` field across paginated responses.
 * - Export CSV: clicking the dropdown triggers a download of the export
 *   endpoint, carrying the active filters as query params.
 */

test.describe('flow: audit filters + export', () => {
  test('actor filter is reflected in the URL and the issued request', async ({ page }) => {
    await mockAdminAuth(page);
    await mockSseSilent(page);

    const events = [
      {
        id: 'ae-1',
        ts: new Date(Date.now() - 60_000).toISOString(),
        actor: 'alice@test.local',
        action: 'command.issued' as const,
        target_type: 'command' as const,
        target_id: 'cmd-1',
        target_label: 'shell',
        metadata: {},
      },
      {
        id: 'ae-2',
        ts: new Date(Date.now() - 120_000).toISOString(),
        actor: 'bob@test.local',
        action: 'command.issued' as const,
        target_type: 'command' as const,
        target_id: 'cmd-2',
        target_label: 'shell',
        metadata: {},
      },
    ];

    let lastActorParam: string | null = null;

    await page.route('**/v1/dash/audit**', (route: Route) => {
      const url = new URL(route.request().url());
      // /audit/export goes through a different handler below; let it pass.
      if (url.pathname.endsWith('/audit/export')) return route.fallback();
      const actor = url.searchParams.get('actor');
      lastActorParam = actor;
      const filtered = actor
        ? events.filter((e) => e.actor.toLowerCase() === actor.toLowerCase())
        : events;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          events: filtered,
          next_cursor: null,
          total: filtered.length,
          limit: 100,
          offset: 0,
          has_more: false,
        }),
      });
    });

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

    await page.goto('audit');
    await expect(page.getByRole('heading', { name: 'Audit log' })).toBeVisible();

    // Both rows visible initially.
    await expect(page.getByTestId('audit-event')).toHaveCount(2);
    await expect(page.getByTestId('audit-count')).toHaveText('Showing 2 of 2 events');

    // Type into the actor filter — the URL must update and the next
    // request must carry the actor param.
    await page.getByTestId('audit-actor-filter').fill('alice@test.local');

    // Debounce timer in the page is 250ms; wait for the URL to settle.
    await expect.poll(() => new URL(page.url()).searchParams.get('actor')).toBe('alice@test.local');
    await expect.poll(() => lastActorParam).toBe('alice@test.local');

    // Only the matching row remains.
    await expect(page.getByTestId('audit-event')).toHaveCount(1);
    await expect(page.getByTestId('audit-count')).toHaveText('Showing 1 of 1 events');
  });

  test('export CSV button triggers a download with the active filters', async ({ page }) => {
    await mockAdminAuth(page);
    await mockSseSilent(page);

    await page.route('**/v1/dash/audit**', (route: Route) => {
      const url = new URL(route.request().url());
      if (url.pathname.endsWith('/audit/export')) {
        // The browser dispatches a navigation to this URL on click; reply
        // with a downloadable CSV that includes the actor query param so
        // the test can verify the filter pass-through.
        const actor = url.searchParams.get('actor') ?? '';
        const csv = `timestamp,actor,action,resource_type,resource_id,target_label,payload\n2026-05-26T11:00:00Z,${actor},command.issued,command,cmd-1,shell,{}\n`;
        return route.fulfill({
          status: 200,
          headers: {
            'content-type': 'text/csv; charset=utf-8',
            'content-disposition': 'attachment; filename="audit-export-test.csv"',
          },
          body: csv,
        });
      }
      // Default /v1/dash/audit response (used by the page load).
      return route.fulfill({
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
      });
    });

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

    // Seed the URL with an actor filter so the export carries it through.
    await page.goto('audit?actor=alice@test.local');
    await expect(page.getByRole('heading', { name: 'Audit log' })).toBeVisible();

    // Open the export dropdown.
    await page.getByTestId('audit-export-button').click();

    // Verify the CSV link's href carries the active filters.
    const csvLink = page.getByTestId('audit-export-csv');
    const href = await csvLink.getAttribute('href');
    expect(href).toContain('/v1/dash/audit/export');
    expect(href).toContain('actor=alice%40test.local');
    expect(href).toContain('format=csv');

    // Click triggers a download (a[download]). Playwright's
    // ``waitForEvent('download')`` fires when the browser begins streaming
    // an attachment. The filename suggested by Chromium may fall back to
    // the URL path when route.fulfill bypasses normal content-disposition
    // handling, so we assert on the download URL instead — it must point
    // to the export endpoint with the active filters preserved.
    const downloadPromise = page.waitForEvent('download');
    await csvLink.click();
    const download = await downloadPromise;
    expect(download.url()).toContain('/v1/dash/audit/export');
    expect(download.url()).toContain('format=csv');
    expect(download.url()).toContain('actor=alice');
  });
});
