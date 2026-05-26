# `web/` — Remote-Pulse dashboard (ADR-0009)

SvelteKit 2 + Svelte 5 (runes) + Tailwind v4 + shadcn-svelte SPA, mounted by
the FastAPI server at `/dash-next/` while the v1.0 Jinja dashboard
(`/dash/`) stays live.

Phase 0 ships only the shell, tokens, design system primitives and the
"Hello fleet" landing page. See
[`docs/docs/architecture/adr/ADR-0009-web-dashboard-redesign.md`](../docs/docs/architecture/adr/ADR-0009-web-dashboard-redesign.md)
§7 for the phase plan.

## Prerequisites

- Node **22.x** LTS (pinned via `.nvmrc` + `engines` in `package.json`).
- A running Remote-Pulse server on `http://127.0.0.1:8080` (for dev-mode
  API/auth proxying). `cd server && uv run uvicorn rp_server.main:app
--port 8080 --reload`.

## Common commands

```sh
npm install            # restores deps; commit the resulting lockfile
npm run dev            # vite dev server on :5173, proxies /v1, /auth, /health to :8080
npm run build          # production build into web/build/
npm run preview        # serve the production build locally
npm run check          # svelte-check (type + a11y diagnostics)
npm run lint           # prettier --check + eslint
npm run format         # prettier --write
npm run test           # vitest --run
npm run test:e2e       # Playwright (Phase 5)
npm run test:a11y      # axe-core baseline (Phase 5)
npm run lighthouse     # Lighthouse CI against `vite preview` (Phase 5)
```

## Accessibility & performance (Phase 5)

ADR-0009 Phase 5 wires two CI-checkable quality gates:

### axe-core baseline — `npm run test:a11y`

`tests/e2e/a11y.spec.ts` injects axe-core into every main dashboard route
(`/`, `/hosts`, `/commands`, `/approvals`, `/audit`, `/enroll`,
`/settings`) and writes the raw violations JSON to
`tests/a11y-baseline/<page>.json`. The spec mocks `/auth/me` with an admin
fixture and stubs `/v1/dash/*` with empty payloads so each route reaches
the rendered DOM without the FastAPI backend.

**Baseline mode:** the spec NEVER fails on violations today. The goal of
the first PR is to capture the violation count so reviewers can triage.
Once obvious findings are fixed, the spec flips to fail-on-regression
(see the TODO at the top of the file).

CI: `.github/workflows/a11y.yml` runs the baseline on every PR and
uploads `tests/a11y-baseline/` as an artifact.

### Lighthouse CI — `npm run lighthouse`

`lighthouserc.json` runs Lighthouse against `vite preview` on
`/dash-next/`, `/dash-next/hosts`, `/dash-next/audit`,
`/dash-next/settings` with the `desktop` preset. Assertions are
**warn-only** today; they fail-on-budget once the targets below are met.

CI: `.github/workflows/lighthouse.yml` runs on every PR and uploads
Lighthouse reports to `temporary-public-storage` plus a workflow
artifact.

### Targets (ADR-0009 §7 Phase 5 exit criteria)

| Gate                   | Target                                      |
| ---------------------- | ------------------------------------------- |
| Lighthouse performance | ≥ 0.90                                      |
| Lighthouse a11y        | ≥ 0.90                                      |
| Lighthouse best-pract. | ≥ 0.90                                      |
| WCAG conformance       | 2.1 AA, 0 axe-core critical violations      |
| First paint (3G)       | ≤ 1 s (Lighthouse `first-contentful-paint`) |

Baseline location: `web/tests/a11y-baseline/*.json` (gitignored —
timestamps in the payload would churn the diff on every run). CI
uploads the directory as a workflow artifact, and the a11y test logs
print the per-page violation count so regressions surface in the PR
check output. Run `npm run test:a11y` locally to regenerate.

> Tip: if your machine already has a vite dev server on port 5173 (e.g.
> another project), set `PW_PORT=5273` (or any free port) to run the
> a11y suite against a separate instance:
>
> ```sh
> PW_PORT=5273 npm run test:a11y
> ```

## Layout

```
web/
├── src/
│   ├── app.css                # Tailwind v4 entry + @theme bridge to tokens
│   ├── app.html               # Pre-paint theme bootstrap (no FOUC)
│   ├── lib/
│   │   ├── api.ts             # Typed fetch wrapper (cookie-based auth)
│   │   ├── utils.ts           # `cn()` helper (clsx + tailwind-merge)
│   │   ├── styles/tokens.css  # Radix Colors → semantic CSS vars (ADR §6.1)
│   │   ├── stores/            # Svelte 5 rune stores: user, theme
│   │   └── components/
│   │       ├── ui/            # shadcn-svelte primitives
│   │       └── app/           # NavBar, ThemeToggle, UserMenu, …
│   └── routes/                # SvelteKit file-based routes
├── static/                    # favicon, robots.txt
├── tests/e2e/                 # Playwright specs (Phase 5)
├── components.json            # shadcn-svelte CLI config
├── svelte.config.js           # adapter-static, base = /dash-next
└── vite.config.ts             # tailwindcss + sveltekit + dev proxy
```

## Build pipeline

`scripts/build_dashboard.sh` (at the repo root) wraps `npm ci && npm run
build` and rsyncs `web/build/` into `server/src/rp_server/static/dash-next/`,
which FastAPI then serves at `/dash-next/`. CI does the same on every PR;
the built output is **not** committed.

## Auth

The SPA is gated by the same OIDC cookie (`rp_session`) that the rest of
the dashboard uses. The root `+layout.ts` calls `GET /auth/me`; if the
response says `authenticated: false`, the SPA does a full-page redirect to
`/auth/login?next=<current>` and the FastAPI OIDC flow takes over.

## Theme

`light` / `dark` / `system` cycle. The pre-paint script in `app.html`
applies the stored preference (`localStorage['rp-theme']`) before first
paint to avoid FOUC. See `src/lib/stores/theme.svelte.ts`.
