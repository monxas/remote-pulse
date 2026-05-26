import type { Page, Route } from '@playwright/test';

/**
 * Auth + ambient mocks shared by every flow spec.
 *
 * The SPA's root layout (`+layout.ts`) calls `GET /auth/me` on mount and
 * full-page-redirects to `/auth/login` when the response says
 * `authenticated: false`. Mocking `/auth/me` with an admin payload keeps
 * the SPA inside SvelteKit's router for the entire test.
 *
 * `/v1/dash/stream` (SSE) is mocked with an empty event stream so the
 * `LiveBadge` mount does not leave an open connection that holds the
 * page in a "loading network" state for `waitUntil: 'networkidle'`.
 */

export interface MockUser {
  user_id?: string;
  user_email?: string;
  user_role?: 'admin' | 'operator' | 'viewer';
}

export async function mockAdminAuth(page: Page, override: MockUser = {}): Promise<void> {
  await page.route('**/auth/me', (route: Route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        user_id: override.user_id ?? '11111111-1111-1111-1111-111111111111',
        user_email: override.user_email ?? 'admin@test.local',
        user_role: override.user_role ?? 'admin',
        authenticated: true,
      }),
    }),
  );
}

export async function mockSseSilent(page: Page): Promise<void> {
  // Respond with an empty event stream. The SSE bridge first does a HEAD
  // probe; respond with 200 to both verbs.
  await page.route('**/v1/dash/stream', (route: Route) => {
    if (route.request().method() === 'HEAD') {
      return route.fulfill({ status: 200, body: '' });
    }
    return route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: '',
    });
  });
}
