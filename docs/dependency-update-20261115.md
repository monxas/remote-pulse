# Dependency update — 2026-11-15

The maintenance and security PRs are integrated together so their overlapping locks cannot undo one another. SQLAlchemy now explicitly requests its asyncio extra, which supplies greenlet required by the server.

The dashboard uses SvelteKit 3, TypeScript 6, adapter-static 4 and the updated Svelte/Vite ecosystem. Migration follows https://svelte.dev/docs/kit/migrating-to-sveltekit-3: plugin configuration is in vite.config.ts, #lib imports include extensions, page state uses $app/state, URL edits clone the read-only query, and navigation uses reset/replace. Internal destinations remain within the /dash-next mount. All browser navigation targets are existing dashboard routes; authentication still uses full browser navigation to FastAPI.

The manual migration review found no cross-origin static-asset dependency, server-side form actions, parameter matchers or 204-body consumers requiring changes. API empty-response handling remains unchanged. Playwright and axe use the same Playwright core version. The previous generated broad migration checklist is not retained as an open task list.

Local validation uses the CI Node 22 line. Node 26's experimental global localStorage interferes with jsdom's storage fixtures, so its test result is not used as acceptance. The supported CI run passes 194 unit tests, type checking, formatting/lint and the static SPA build. Server validation passes 415 tests, with 6 skipped and 8 Postgres-marked tests reserved for the real isolated CI database. No live server or agent has been restarted.
