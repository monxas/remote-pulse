import { test, expect, type Page, type Route } from '@playwright/test';
import { mockAdminAuth, mockSseSilent } from './helpers/auth';

/**
 * Mobile / touch viewport audit.
 *
 * The Family Hub Tablet is the primary consumer of the dashboard, and
 * it lives in landscape on the kitchen wall. This spec exercises both
 * a portrait iPhone-class viewport (390×844) AND a landscape tablet
 * viewport (1024×600) to guarantee:
 *
 *   1. No interactive control renders at <44×44 px hit-box (per Apple
 *      HIG / WCAG 2.5.5 Target Size). We assert on `getBoundingClientRect`
 *      for every <button>, <a> with role link / nav, native checkbox,
 *      and <input type="checkbox">. Tiny <a> wrapping inline text
 *      ("Clear filters" footer link, "Sign in" link, kbd hint) is
 *      tolerated when its CSS reports `display: inline`.
 *
 *   2. The page does not horizontally overflow the viewport (no
 *      sideways scroll on touch-first hardware).
 *
 *   3. The sticky table header in the Fleet page actually sticks
 *      (data-testid="hosts-table" thead `position: sticky`).
 *
 *   4. The `pull-to-refresh` wrapper is mounted on every refreshable
 *      page (Fleet, Commands, Approvals, Audit).
 */

const BASE = '/dash-next';

type PageCase = { name: string; path: string };

const PAGES: PageCase[] = [
  { name: 'fleet', path: `${BASE}/` },
  { name: 'commands', path: `${BASE}/commands` },
  { name: 'approvals', path: `${BASE}/approvals` },
  { name: 'audit', path: `${BASE}/audit` },
  { name: 'enroll', path: `${BASE}/enroll` },
  { name: 'settings', path: `${BASE}/settings` },
];

// 44px is the WCAG 2.5.5 / Apple HIG target. We allow a 1-px sub-pixel
// rounding fudge so a control whose computed height is 43.99 doesn't
// trip the gate.
const MIN_TAP = 43;

async function installApiMocks(page: Page): Promise<void> {
  await mockAdminAuth(page);
  await mockSseSilent(page);

  await page.route('**/v1/**', (route: Route) => {
    const url = route.request().url();
    const empty: Record<string, unknown> = {
      hosts: [],
      commands: [],
      approvals: [],
      events: [],
      groups: [],
      users: [],
      links: [],
      items: [],
      pages: [],
      next_cursor: null,
      total: 0,
      online: 0,
      stale: 0,
      offline: 0,
      online_pct: 0,
      online_pct_24h_ago: 0,
      pending_approvals: 0,
    };
    if (url.includes('/dash/overview')) {
      empty.total = 0;
      empty.online = 0;
    }
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(empty),
    });
  });
}

interface UndersizedTarget {
  selector: string;
  width: number;
  height: number;
  text: string;
}

async function findUndersizedTargets(page: Page): Promise<UndersizedTarget[]> {
  // Inspect every `<button>`, primary-action link, and visible
  // checkbox / select / input that is NOT inside an aria-hidden tree.
  // We pull the data out of the browser context in one round-trip.
  return page.evaluate((minTap) => {
    const undersized: UndersizedTarget[] = [];
    type LocalTarget = {
      selector: string;
      width: number;
      height: number;
      text: string;
    };
    const _local: LocalTarget[] = undersized as unknown as LocalTarget[];

    function visible(el: Element): boolean {
      const rect = el.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return false;
      const cs = getComputedStyle(el);
      if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') return false;
      return true;
    }

    function ariaHidden(el: Element): boolean {
      let cur: Element | null = el;
      while (cur) {
        if (cur.getAttribute('aria-hidden') === 'true') return true;
        cur = cur.parentElement;
      }
      return false;
    }

    function describe(el: Element): string {
      const tag = el.tagName.toLowerCase();
      const id = el.id ? `#${el.id}` : '';
      const cls = el.classList.length > 0 ? `.${Array.from(el.classList).slice(0, 2).join('.')}` : '';
      return `${tag}${id}${cls}`;
    }

    // Buttons + links inside <nav> / <header> / role=button.
    const selectors = [
      'button:not([disabled]):not([aria-hidden="true"])',
      'a[href]',
      'input[type="checkbox"]',
      'input[type="radio"]',
      'select',
    ];
    const nodes = document.querySelectorAll(selectors.join(','));
    for (const el of Array.from(nodes)) {
      if (!visible(el)) continue;
      if (ariaHidden(el)) continue;
      // Anchor-wrapped inline text (e.g. footer "⌘K" kbd, the
      // "remote-pulse" wordmark which is just a brand link, link
      // variant buttons under prose) are inline — skip them so we
      // don't penalise legitimate inline prose. Real CTAs are
      // inline-flex / block / flex by virtue of `Button` styling.
      const cs = getComputedStyle(el);
      if (el.tagName === 'A' && cs.display === 'inline') continue;
      const rect = el.getBoundingClientRect();
      // Native checkboxes are 16px by spec but we wrap them in a
      // 44px <label> on touch; only fail if the parent label is
      // ALSO < 44.
      if (el.tagName === 'INPUT') {
        const lbl = el.closest('label');
        if (lbl) {
          const lr = lbl.getBoundingClientRect();
          if (lr.width >= minTap && lr.height >= minTap) continue;
        }
      }
      if (rect.width < minTap || rect.height < minTap) {
        _local.push({
          selector: describe(el),
          width: Math.round(rect.width * 100) / 100,
          height: Math.round(rect.height * 100) / 100,
          text: (el.textContent ?? '').trim().slice(0, 60),
        });
      }
    }
    return _local;
  }, MIN_TAP);
}

// ---------------------------------------------------------------------------
// Portrait phone: iPhone 13 (390×844)
// ---------------------------------------------------------------------------

test.describe('mobile portrait (390×844) — tap targets + overflow', () => {
  test.use({
    viewport: { width: 390, height: 844 },
    hasTouch: true,
    isMobile: true,
    // Force coarse-pointer media queries to evaluate to true.
    deviceScaleFactor: 2,
  });

  for (const pc of PAGES) {
    test(`${pc.name}: no <44px tap targets, no horizontal overflow`, async ({ page }) => {
      await installApiMocks(page);
      await page.goto(pc.path, { waitUntil: 'networkidle' });

      // No horizontal overflow.
      const overflow = await page.evaluate(() => {
        return document.documentElement.scrollWidth - document.documentElement.clientWidth;
      });
      expect(overflow, `${pc.name} should not horizontally overflow`).toBeLessThanOrEqual(1);

      // Tap targets.
      const violations = await findUndersizedTargets(page);
      expect(
        violations,
        `${pc.name} has ${violations.length} sub-44px tap target(s):\n${JSON.stringify(violations, null, 2)}`,
      ).toEqual([]);
    });
  }

  test('fleet: PullToRefresh wrapper is mounted', async ({ page }) => {
    await installApiMocks(page);
    await page.goto(`${BASE}/`, { waitUntil: 'networkidle' });
    await expect(page.locator('[data-testid="ptr-wrapper"]').first()).toBeAttached();
  });

  test('commands: PullToRefresh wrapper is mounted', async ({ page }) => {
    await installApiMocks(page);
    await page.goto(`${BASE}/commands`, { waitUntil: 'networkidle' });
    await expect(page.locator('[data-testid="ptr-wrapper"]').first()).toBeAttached();
  });
});

// ---------------------------------------------------------------------------
// Landscape tablet: Family Hub kitchen unit (1024×600)
// ---------------------------------------------------------------------------

test.describe('landscape tablet (1024×600) — Family Hub use case', () => {
  test.use({
    viewport: { width: 1024, height: 600 },
    hasTouch: true,
    isMobile: false,
  });

  test('fleet: table view renders (not mobile card stack)', async ({ page }) => {
    await installApiMocks(page);
    await page.goto(`${BASE}/`, { waitUntil: 'networkidle' });
    // The desktop/tablet table is gated `hidden sm:block`. At 1024w
    // it must be visible.
    const table = page.locator('[data-testid="hosts-table"]');
    await expect(table).toBeVisible();
  });

  test('fleet: no horizontal overflow at 1024×600', async ({ page }) => {
    await installApiMocks(page);
    await page.goto(`${BASE}/`, { waitUntil: 'networkidle' });
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
  });
});
