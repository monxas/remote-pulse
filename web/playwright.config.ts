import { defineConfig, devices } from '@playwright/test';

/**
 * Phase 5 (ADR-0009): real E2E flows are now wired. The SvelteKit app is
 * mounted at `/dash-next/` (see `svelte.config.js` -> `paths.base`), so
 * we set `baseURL` to that prefix. This lets specs `page.goto('/')`,
 * `page.goto('/settings')`, etc. without spelling the base every time.
 *
 * `webServer.url` is the readiness probe; pointing it at the prefix
 * matches the URL the SPA actually serves (the bare `/` hands back the
 * dev-server's "did you mean to visit /dash-next" 404 page, not the SPA
 * shell). Without this fix, smoke tests that rely on the SPA mounting
 * never see `data-testid` markers and time out.
 *
 * The port + base host are env-overridable via `PW_PORT` so the a11y
 * baseline run can side-step a developer's pre-existing vite on :5173
 * (commonly held by other projects on the same workstation).
 */
const PORT = Number(process.env.PW_PORT ?? 5173);
const HOST = `http://127.0.0.1:${PORT}`;
// NOTE: trailing slash is significant. Playwright resolves `page.goto()`
// via the URL constructor; a base URL without a trailing slash drops the
// last path segment when combined with a relative path. With the slash,
// `page.goto('settings')` resolves to `/dash-next/settings`, and absolute
// paths like `page.goto('/dash-next/hosts')` (used by `a11y.spec.ts`)
// still resolve correctly because a leading slash means origin-relative.
const BASE_URL = `${HOST}/dash-next/`;

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
  },
  webServer: {
    command: `npm run dev -- --port ${PORT} --strictPort --host 127.0.0.1`,
    url: `${HOST}/dash-next/`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
