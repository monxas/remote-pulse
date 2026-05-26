import { test, expect, type Page, type Route } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { mkdir, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

/**
 * Phase 5 (ADR-0009) — axe-core accessibility gate.
 *
 * FAIL-ON-REGRESSION MODE: as of v1.0.5 every main dashboard route is
 * scanned against WCAG 2.0/2.1 A + AA tags and the test fails if axe
 * reports any violations. The raw axe payload is still written to
 * `web/tests/a11y-baseline/<page>.json` for debugging context and to
 * keep the report shape stable for future tooling, but it is no longer
 * the source of truth — the assertion below is.
 *
 * If you legitimately need to introduce a violation (e.g. a third-party
 * embed that ships its own a11y debt), prefer fixing it; otherwise scope
 * an axe disable rule to the specific selector/page in this spec rather
 * than weakening the global gate.
 *
 * AUTH: every page (except `/auth/login`) requires an authenticated OIDC
 * session. The dashboard's `+layout.ts` calls `GET /auth/me` on first paint
 * and redirects to `/auth/login?next=…` when unauthenticated, which leaves
 * the SPA entirely and breaks axe runs. We mirror the auth pattern used by
 * `settings.spec.ts`: intercept `/auth/me` with an admin fixture and stub
 * the `/v1/dash/*` endpoints each page calls on mount with empty-but-valid
 * payloads so the SPA reaches the rendered DOM and axe has something to
 * inspect.
 */

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const BASELINE_DIR = resolve(__dirname, '..', 'a11y-baseline');

const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'];

// Base path matches `svelte.config.js` -> `paths.base = '/dash-next'`.
// The Vite dev server (playwright `webServer`) still serves the SPA at the
// configured base, so navigate using the full base-prefixed path.
const BASE = '/dash-next';

interface PageCase {
  name: string;
  path: string;
  // Pages that don't require auth (none today, but keep the door open).
  publicPage?: boolean;
}

const PAGES: PageCase[] = [
  { name: 'fleet-overview', path: `${BASE}/` },
  { name: 'hosts', path: `${BASE}/hosts` },
  { name: 'commands', path: `${BASE}/commands` },
  { name: 'approvals', path: `${BASE}/approvals` },
  { name: 'audit', path: `${BASE}/audit` },
  { name: 'enroll', path: `${BASE}/enroll` },
  { name: 'settings', path: `${BASE}/settings` },
];

/**
 * Install network mocks: admin `/auth/me`, plus catch-all empty fixtures
 * for every `/v1/dash/*` and `/v1/enrollment-links*` request. We don't try
 * to render meaningful data here — the goal is to get the route's DOM up
 * so axe can scan the actual chrome (nav, headings, buttons, forms, …).
 */
async function installAuthAndApiMocks(page: Page): Promise<void> {
  await page.route('**/auth/me', (route: Route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        user_id: '11111111-1111-1111-1111-111111111111',
        user_email: 'a11y@test.local',
        user_role: 'admin',
        authenticated: true,
      }),
    }),
  );

  // SSE stream: respond with an empty event stream so the page mounts
  // without a hanging connection blocking axe's scan.
  await page.route('**/v1/dash/stream', (route: Route) =>
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: '',
    }),
  );

  // Generic JSON fallback for every `/v1/*` GET. Returns the shape the SPA
  // most commonly expects: a top-level array under a plural key, plus a
  // few well-known fields. Routes that need richer fixtures override
  // explicitly below.
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
      total_hosts: 0,
      online_hosts: 0,
      stale_hosts: 0,
      pending_commands: 0,
      next_cursor: null,
    };
    // Per-endpoint hinting: some pages key off specific top-level fields.
    if (url.includes('/dash/overview')) {
      empty.total_hosts = 0;
    }
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(empty),
    });
  });
}

test.describe('axe-core a11y baseline (Phase 5)', () => {
  test.beforeAll(async () => {
    await mkdir(BASELINE_DIR, { recursive: true });
  });

  for (const pc of PAGES) {
    test(`baseline: ${pc.name} (${pc.path})`, async ({ page }) => {
      if (!pc.publicPage) {
        await installAuthAndApiMocks(page);
      }

      // Capture console errors for the baseline payload — useful context
      // when reviewing axe output later.
      const consoleErrors: string[] = [];
      page.on('pageerror', (err) => consoleErrors.push(String(err)));
      page.on('console', (msg) => {
        if (msg.type() === 'error') consoleErrors.push(msg.text());
      });

      await page.goto(pc.path, { waitUntil: 'networkidle' });

      // Sanity: the SPA root must be in the DOM. If auth redirect kicked
      // in (login page outside the SPA) we won't have `<main>` or the
      // app shell, which would make axe results meaningless.
      const bodyReady = await page.locator('body').isVisible();
      expect(bodyReady).toBe(true);

      const results = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();

      const payload = {
        page: pc.name,
        path: pc.path,
        url: results.url,
        timestamp: results.timestamp,
        toolOptions: results.toolOptions,
        testEngine: results.testEngine,
        testRunner: results.testRunner,
        testEnvironment: results.testEnvironment,
        tags: WCAG_TAGS,
        counts: {
          violations: results.violations.length,
          incomplete: results.incomplete.length,
          passes: results.passes.length,
          inapplicable: results.inapplicable.length,
        },
        violations: results.violations,
        incomplete: results.incomplete,
        consoleErrors,
      };

      const outPath = resolve(BASELINE_DIR, `${pc.name}.json`);
      await writeFile(outPath, JSON.stringify(payload, null, 2), 'utf8');

      // Fail-on-regression: a one-line summary for CI logs, then the
      // hard assertion. We surface the offending rule IDs + selectors in
      // the failure message so reviewers don't have to dig into the JSON
      // payload to know what regressed.
      console.log(
        `[a11y] ${pc.name}: ${results.violations.length} violations, ${results.incomplete.length} incomplete -> ${outPath}`,
      );
      const summary = results.violations.map((v) => ({
        id: v.id,
        impact: v.impact,
        help: v.help,
        nodes: v.nodes.map((n) => ({ target: n.target, html: n.html })),
      }));
      expect(summary, `axe violations on ${pc.name}`).toEqual([]);
    });
  }
});
