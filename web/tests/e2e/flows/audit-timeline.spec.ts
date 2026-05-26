import { test, expect, type Route } from '@playwright/test';
import { mockAdminAuth, mockSseSilent } from '../helpers/auth';

/**
 * Flow 7 — Audit timeline (Phase 2).
 *
 * Verifies the audit page renders a mixed feed of action types in ts
 * DESC order, with the per-action tone dot and label/icon. Then we
 * exercise the action-filter chip ("settings.group.create") and assert
 * the list narrows to the matching event. Finally we expand the
 * `<details>` block to confirm the metadata payload surfaces.
 */

test.describe('flow: audit timeline', () => {
  test('admin sees mixed action types in DESC order and can filter by action', async ({
    page,
  }) => {
    await mockAdminAuth(page);
    await mockSseSilent(page);

    const tsNow = Date.now();
    const iso = (offsetMs: number) => new Date(tsNow - offsetMs).toISOString();

    // Three events of distinct action types. DESC ordered by `ts`:
    //  1) command.issued (most recent)
    //  2) settings.group.create
    //  3) host.enrolled (oldest)
    const events = [
      {
        id: 'ae-1',
        ts: iso(60_000),
        actor: 'admin@test.local',
        action: 'command.issued' as const,
        target_type: 'command' as const,
        target_id: 'cmd-audit-1',
        target_label: 'shell',
        metadata: { cmd: 'uptime' },
      },
      {
        id: 'ae-2',
        ts: iso(5 * 60_000),
        actor: 'admin@test.local',
        action: 'settings.group.create' as const,
        target_type: 'group' as const,
        target_id: 'grp-new',
        target_label: 'stage',
        metadata: { description: 'staging fleet' },
      },
      {
        id: 'ae-3',
        ts: iso(60 * 60_000),
        actor: 'system',
        action: 'host.enrolled' as const,
        target_type: 'host' as const,
        target_id: 'host-new',
        target_label: 'rp-new-1',
        metadata: {},
      },
    ];

    let lastActionFilter: string[] = [];

    await page.route('**/v1/dash/audit**', (route: Route) => {
      const url = new URL(route.request().url());
      const actions = url.searchParams.getAll('action');
      lastActionFilter = actions;
      const filtered =
        actions.length === 0 ? events : events.filter((e) => actions.includes(e.action));
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ events: filtered, next_cursor: null }),
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

    // All three events render.
    const allRows = page.getByTestId('audit-event');
    await expect(allRows).toHaveCount(3);

    // Verify ts DESC order via the `data-action` attribute on each <li>.
    const orderedActions = await allRows.evaluateAll((nodes) =>
      nodes.map((n) => (n as HTMLElement).dataset.action ?? ''),
    );
    expect(orderedActions).toEqual([
      'command.issued',
      'settings.group.create',
      'host.enrolled',
    ]);

    // Tone-based dot icons surface per ACTION_TONE table. We assert the
    // visible action-label texts emitted by `AuditEvent.svelte`.
    await expect(page.getByText('issued command')).toBeVisible();
    await expect(page.getByText('created group')).toBeVisible();
    await expect(page.getByText('enrolled host')).toBeVisible();

    // Filter chip: click "settings.group.create". The chips are
    // role-less buttons inside the filter bar; identify by their
    // unique mono-font label.
    await page.getByRole('button', { name: 'settings.group.create', exact: true }).click();
    await expect.poll(() => lastActionFilter).toEqual(['settings.group.create']);

    // Only the matching row remains.
    await expect(page.getByTestId('audit-event')).toHaveCount(1);
    await expect(page.getByTestId('audit-event').first()).toHaveAttribute(
      'data-action',
      'settings.group.create',
    );

    // Expand the metadata <details>: the chip is unique on the page.
    await page.getByText('metadata').click();
    await expect(page.getByText(/"description"/)).toBeVisible();
    await expect(page.getByText(/"staging fleet"/)).toBeVisible();
  });
});
