import { test, expect, type Route } from '@playwright/test';
import { mockAdminAuth } from '../helpers/auth';
import { installFakeEventSource, mockSseHead, pushSseEvent } from '../helpers/sse-stream';

/**
 * Flow — browser notifications opt-in via Settings → Notifications.
 *
 * Verifies the in-app, SSE-driven notification path:
 *   1. Settings page exposes a third tab "Notifications".
 *   2. Permission flow: default → granted (mocked) → options revealed.
 *   3. Opt-in checkboxes persist to localStorage.
 *   4. An SSE `command.status_change` with status=failed, while the tab
 *      is *unfocused*, fires a `new Notification(...)` — we observe this
 *      by replacing `window.Notification` with a recording stub before
 *      the SPA boots, since Playwright can't intercept the native
 *      constructor.
 *
 * Note on focus: the dispatcher uses `document.visibilityState` +
 * `document.hasFocus()` to gate. In Playwright headless the tab is
 * focused by default; we stub `document.hasFocus` to return `false`
 * to simulate the "tab in the background" case the feature targets.
 */

const EMPTY_JSON = (body: unknown) => ({
  status: 200,
  contentType: 'application/json',
  body: JSON.stringify(body),
});

async function installNotificationStub(page: import('@playwright/test').Page): Promise<void> {
  // Replace `window.Notification` BEFORE the SPA loads. The stub records
  // every constructor call into `window.__rpNotifications` so the test
  // can assert on it. We also force `document.hasFocus()` to return
  // false so the dispatcher's "tab is focused" gate doesn't suppress
  // the fire in headless mode.
  await page.addInitScript(() => {
    type Captured = { title: string; options: NotificationOptions | undefined };
    const captured: Captured[] = [];
    (window as unknown as { __rpNotifications: Captured[] }).__rpNotifications = captured;

    class StubNotification extends EventTarget {
      static permission: NotificationPermission = 'granted';
      static requestPermission = async (): Promise<NotificationPermission> => 'granted';
      static maxActions = 0;
      title: string;
      body: string;
      tag: string | undefined;
      icon: string | undefined;
      onclick: ((this: Notification, ev: Event) => unknown) | null = null;
      onclose: ((this: Notification, ev: Event) => unknown) | null = null;
      onerror: ((this: Notification, ev: Event) => unknown) | null = null;
      onshow: ((this: Notification, ev: Event) => unknown) | null = null;

      constructor(title: string, options?: NotificationOptions) {
        super();
        this.title = title;
        this.body = options?.body ?? '';
        this.tag = options?.tag;
        this.icon = options?.icon;
        captured.push({ title, options });
      }
      close(): void {
        // no-op
      }
    }
    (window as unknown as { Notification: typeof StubNotification }).Notification =
      StubNotification;
    Object.defineProperty(document, 'hasFocus', {
      configurable: true,
      value: () => false,
    });
    Object.defineProperty(document, 'visibilityState', {
      configurable: true,
      get: () => 'hidden',
    });
  });
}

test.describe('flow: browser notifications opt-in', () => {
  test.beforeEach(async ({ page }) => {
    await installNotificationStub(page);
    await mockAdminAuth(page);
    await installFakeEventSource(page);
    await mockSseHead(page);

    await page.route('**/v1/dash/overview', (route: Route) =>
      route.fulfill(
        EMPTY_JSON({
          total: 0,
          online: 0,
          stale: 0,
          offline: 0,
          pending_approvals: 0,
          online_pct: 0,
          online_pct_24h_ago: 0,
        }),
      ),
    );
    await page.route('**/v1/dash/hosts**', (route: Route) =>
      route.fulfill(EMPTY_JSON({ hosts: [] })),
    );
    await page.route('**/v1/dash/commands**', (route: Route) =>
      route.fulfill(EMPTY_JSON({ commands: [], next_cursor: null })),
    );
    await page.route('**/v1/dash/audit**', (route: Route) =>
      route.fulfill(EMPTY_JSON({ events: [], next_cursor: null })),
    );
    await page.route('**/v1/dash/approvals/pending', (route: Route) =>
      route.fulfill(EMPTY_JSON({ approvals: [] })),
    );
    await page.route('**/v1/dash/settings/groups', (route: Route) =>
      route.fulfill(EMPTY_JSON({ groups: [] })),
    );
    await page.route('**/v1/dash/settings/users', (route: Route) =>
      route.fulfill(EMPTY_JSON({ users: [] })),
    );
  });

  test('Settings exposes Notifications tab with permission flow', async ({ page }) => {
    await page.goto('/settings');
    const tab = page.getByTestId('tab-notifications');
    await expect(tab).toBeVisible();
    await tab.click();

    // Permission was pre-set to 'granted' by the stub so the options
    // block renders immediately — no need to click "Enable" first.
    await expect(page.getByTestId('notifications-enabled-badge')).toBeVisible();
    await expect(page.getByTestId('notifications-options')).toBeVisible();

    // Sanity: a default-OFF row starts unchecked.
    const offlineOptIn = page.getByTestId('opt-in-host.offline');
    await expect(offlineOptIn).not.toBeChecked();

    // Toggle it ON and confirm.
    await offlineOptIn.check();
    await expect(offlineOptIn).toBeChecked();

    // Reload the tab and confirm persistence via localStorage.
    await page.reload();
    await page.getByTestId('tab-notifications').click();
    await expect(page.getByTestId('opt-in-host.offline')).toBeChecked();
  });

  test('SSE command.failed event fires a native Notification when unfocused', async ({ page }) => {
    await page.goto('/settings');
    await page.getByTestId('tab-notifications').click();
    await expect(page.getByTestId('notifications-options')).toBeVisible();

    // "Command failed" is default-ON, so we don't toggle anything.
    await pushSseEvent(
      page,
      'command.status_change',
      {
        command_id: 'cmd-1',
        host_id: 'host-1',
        hostname: 'rp-prod-1',
        status: 'failed',
        exit_code: 1,
        stderr: 'boom',
      },
      'delivery-1',
    );

    // The dispatcher reads `document.hasFocus()` (we stubbed to false)
    // and fires `new Notification(...)`. Wait for the stub to record it.
    await expect
      .poll(async () =>
        page.evaluate(() => {
          const w = window as unknown as {
            __rpNotifications?: Array<{ title: string }>;
          };
          return w.__rpNotifications?.length ?? 0;
        }),
      )
      .toBeGreaterThan(0);

    const captured = await page.evaluate(() => {
      const w = window as unknown as {
        __rpNotifications: Array<{ title: string; options: NotificationOptions }>;
      };
      return w.__rpNotifications;
    });
    expect(captured.length).toBeGreaterThan(0);
    const first = captured[0]!;
    expect(first.title).toContain('rp-prod-1');
    expect(first.title).toContain('failed');
    expect(first.options?.tag).toBe('delivery-1');
  });

  test('opting out of a category suppresses its Notification', async ({ page }) => {
    await page.goto('/settings');
    await page.getByTestId('tab-notifications').click();
    await expect(page.getByTestId('notifications-options')).toBeVisible();

    // Turn the default-ON "Command failed" OFF.
    const failedOptIn = page.getByTestId('opt-in-command.failed');
    await expect(failedOptIn).toBeChecked();
    await failedOptIn.uncheck();

    await pushSseEvent(
      page,
      'command.status_change',
      { command_id: 'cmd-2', hostname: 'rp-x', status: 'failed', exit_code: 1 },
      'delivery-2',
    );

    // Give the dispatcher a tick to (not) fire.
    await page.waitForTimeout(150);
    const count = await page.evaluate(() => {
      const w = window as unknown as { __rpNotifications?: unknown[] };
      return w.__rpNotifications?.length ?? 0;
    });
    expect(count).toBe(0);
  });
});
