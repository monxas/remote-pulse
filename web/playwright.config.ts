import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright is installed in Phase 0 so the dependency lands in the
 * lockfile early. Phase 5 (per ADR-0009 §7) wires the E2E flows; until
 * then this config only points at the SvelteKit dev server so
 * `npx playwright test` runs locally without surprises.
 */
export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: 'http://127.0.0.1:5173',
    trace: 'on-first-retry',
  },
  webServer: {
    command: 'npm run dev',
    url: 'http://127.0.0.1:5173',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
