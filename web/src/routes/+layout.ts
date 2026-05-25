import type { LayoutLoad } from './$types';
import { browser } from '$app/environment';
import { ApiError, getAuthMe, type AuthMe } from '$lib/api';
import { userStore } from '$lib/stores/user.svelte';

// Static SPA — every load is client-side. No prerender, no SSR.
export const prerender = false;
export const ssr = false;
export const csr = true;

/**
 * Root layout load: bootstrap the authenticated session.
 *
 * On first paint we hit `/auth/me`. The FastAPI server returns an OIDC-
 * backed JSON whoami; if the user is not authenticated it still returns
 * 200 with `authenticated: false`. In that case we redirect to
 * `/auth/login?next=<current>` (full page nav — leaves the SPA — because
 * the OIDC dance lives on the FastAPI side).
 *
 * If the auth endpoint itself errors (e.g. server cold start), we degrade
 * to "unauthenticated" rather than crash the SPA boot.
 */
export const load: LayoutLoad = async ({ fetch, url }): Promise<{ user: AuthMe | null }> => {
  if (!browser) {
    return { user: null };
  }

  let me: AuthMe | null = null;
  try {
    me = await getAuthMe(fetch);
  } catch (err) {
    // 401 / network: treat as unauthenticated. Redirect handled below so
    // the user lands on the login page rather than a blank shell.
    if (!(err instanceof ApiError)) {
      console.error('auth/me failed', err);
    }
  }

  if (!me?.authenticated) {
    // `/auth/login` is served by FastAPI, not SvelteKit, so we need a full
    // page navigation here. `goto()` would stay inside the SPA router and
    // 404. The OIDC callback honours `next` (auth_oidc.py) and 302s back.
    const next = encodeURIComponent(url.pathname + url.search);
    window.location.assign(`/auth/login?next=${next}`);
    return { user: null };
  }

  userStore.set(me);
  return { user: me };
};
