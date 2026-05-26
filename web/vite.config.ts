import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vitest/config';

// Tailwind v4 is wired as a Vite plugin — no PostCSS pipeline, no
// `tailwind.config.js`. All config lives in `src/app.css` via `@theme`
// and `@import "tailwindcss"`. See ADR-0009 §3.2.
//
// We import `defineConfig` from `vitest/config` so the `test` block is
// type-checked. Vite 8 dropped the inline `test` property from its own
// `UserConfigExport`.
export default defineConfig({
  plugins: [tailwindcss(), sveltekit()],
  server: {
    port: 5173,
    strictPort: false,
    // Local dev: hit `/v1/*`, `/auth/*`, `/health` against the FastAPI
    // server on :8080 so the SPA experience matches production where the
    // SPA and the API share an origin behind Caddy. README documents the
    // expected `uvicorn rp_server.main:app --port 8080` setup.
    proxy: {
      '/v1': 'http://127.0.0.1:8080',
      '/auth': 'http://127.0.0.1:8080',
      '/health': 'http://127.0.0.1:8080',
      '/metrics': 'http://127.0.0.1:8080',
    },
  },
  test: {
    include: ['src/**/*.{test,spec}.{js,ts}'],
    environment: 'jsdom',
    globals: true,
    // Svelte 5 component tests via @testing-library/svelte need the
    // client-side build of Svelte. Without these conditions Vite
    // resolves `svelte` to `index-server.js` and `mount()` throws
    // `lifecycle_function_unavailable`.
    server: {
      deps: {
        inline: ['@testing-library/svelte'],
      },
    },
  },
  resolve: {
    conditions: ['browser'],
  },
});
