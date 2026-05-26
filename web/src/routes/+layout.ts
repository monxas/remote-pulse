import type { LayoutLoad } from './$types';
import { browser } from '$app/environment';
import { ApiError, getAuthMe, type AuthMe } from '$lib/api';
import { userStore } from '$lib/stores/user.svelte';

// Static SPA — every load is client-side. No prerender, no SSR.
export const prerender = false;
export const ssr = false;
export const csr = true;

// Lighthouse CI bypass: compiled out unless the SPA is built with
// `VITE_LH_BYPASS=1`. Production CI/release builds set it to "0" (or just
// don't pass the flag) so the constant is `false` after dead-code-elimination
// and the branch below is stripped from the bundle. Only the dedicated
// Lighthouse workflow builds with the flag on, and it does so with a
// throwaway per-run token. See `.github/workflows/lighthouse.yml` and
// `lighthouserc.json`.
const LH_BYPASS_BUILD_FLAG = import.meta.env.VITE_LH_BYPASS === '1';

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

  // Lighthouse CI short-circuit. Only honored in builds that opt in via
  // VITE_LH_BYPASS=1 *and* receive `?_lh=1` in the URL. Production bundles
  // tree-shake the whole branch (LH_BYPASS_BUILD_FLAG = false). When active
  // we synthesize an admin AuthMe so the SPA shell paints the real authed
  // routes against `vite preview` (where /auth/me is unreachable).
  if (LH_BYPASS_BUILD_FLAG && url.searchParams.get('_lh') === '1') {
    const synthetic: AuthMe = {
      authenticated: true,
      user_id: '00000000-0000-0000-0000-00000000000a',
      user_email: 'lighthouse@test',
      user_role: 'admin',
    };
    userStore.set(synthetic);
    return { user: synthetic };
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
