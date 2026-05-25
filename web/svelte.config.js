import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
  preprocess: vitePreprocess(),
  kit: {
    // Static SPA: every navigation is client-side. `fallback: 'index.html'`
    // tells the adapter to write the SPA shell at index.html so the FastAPI
    // StaticFiles mount (`html=True`) serves it for unknown paths under
    // `/dash-next/` and the client-side router takes over. ADR-0009 §3.8.
    adapter: adapter({
      pages: 'build',
      assets: 'build',
      fallback: 'index.html',
      precompress: false,
      strict: true,
    }),
    // The SPA is mounted at /dash-next/ by FastAPI. Tell SvelteKit so all
    // built asset URLs and client-side navigations carry that prefix.
    paths: {
      base: '/dash-next',
      relative: false,
    },
    // No prerendered pages — every route is dynamic in the SPA sense.
    prerender: {
      entries: [],
    },
  },
};

export default config;
