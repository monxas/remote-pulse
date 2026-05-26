import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright is installed in Phase 0 so the dependency lands in the
 * lockfile early. Phase 5 (per ADR-0009 §7) wires the E2E flows; until
 * then this config only points at the SvelteKit dev server so
 * `npx playwright test` runs locally without surprises.
 *
 * The port + base URL are env-overridable via `PW_PORT` so the a11y
 * baseline run can side-step a developer's pre-existing vite on :5173
 * (commonly held by other projects on the same workstation).
 */
const PORT = Number(process.env.PW_PORT ?? 5173);
const BASE_URL = `http://127.0.0.1:${PORT}`;

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
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
