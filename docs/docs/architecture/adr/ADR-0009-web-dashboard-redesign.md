# ADR-0009: Remote-Pulse Web Dashboard Redesign — SvelteKit SPA + JSON API

**Status:** Accepted
**Date:** 2026-05-25
**Accepted:** 2026-05-25
**Deciders:** Ramón Kamibayashi
**Supersedes (partially):** ADR-0008 §F5 (server-rendered Jinja2 + HTMX + Pico dashboard).
**Technical Story:** Rebuild the Remote-Pulse web UI as a SvelteKit single-page app over a clean JSON API. Full information-architecture overhaul (fleet overview, host detail, commands, approvals, audit log, settings, enroll wizard). Dark-mode-first design system based on Tailwind v4 + shadcn-svelte. Replaces the v1.0.0 GA dashboard shipped in F5.

---

## 1. Context

### 1.1 What we shipped in v1.0.0 GA (F5)

ADR-0008 §F5 delivered a working but minimum-viable dashboard:

- **Render path:** FastAPI → Jinja2 templates → HTML response.
- **Interactivity:** HTMX 2.0 polled every 5 s for table refresh, plus a small `<script>` block that updates the "last seen" timestamp every second.
- **Styling:** Pico CSS 2 (classless, CDN), with `<div style="display:flex;...">` inline overrides where Pico did not give us layout.
- **Charts:** uPlot 1.6 IIFE bundle (CDN), one sparkline per metric per host, hand-wired via DOMContentLoaded.
- **Pages:** `/dash/` only. Host detail and sparkline data render as HTMX partials swapped into the same page. There is no `/hosts/:id`, no `/commands`, no `/approvals`, no `/audit`, no `/settings`. All of those flows exist only as JSON endpoints reachable from the CLI / TUI / Telegram approval bot.
- **Templates total:** 4 files, 247 lines of Jinja2 (see `server/src/rp_server/templates/`).

### 1.2 What is wrong with it

Concrete observations after the first user session (browser console output captured 2026-05-25):

1. **CSP fights the design.** Pico, HTMX, and uPlot are loaded from `unpkg.com` and `jsdelivr.net`; the strict CSP shipped in `main.py` blocks them on first paint. We patched CSP to allow those origins, but the underlying problem is that we have no vendoring story and no build pipeline — every dependency is a CDN script tag.
2. **`favicon.ico` 401.** Static-asset routing is muddled with auth: the dashboard has no favicon, and the auth dependency rejects unauthenticated requests to a path that should be public. Symptom of "no proper static asset story".
3. **No information architecture.** Everything is a single dashboard. Issuing a command, approving one, inspecting an audit trail, or onboarding a host all require leaving the web UI for the CLI/TUI/Telegram bot. The web is a read-only viewer.
4. **No mobile layout.** Pico is responsive but the inline `<div style="display: flex; justify-content: space-between">` header collapses badly on iPhone. The Family Hub tablet (1080p portrait) renders a useable but ugly view. Touch targets are below 44px in places.
5. **No dark mode.** Pico's auto-theme follows `prefers-color-scheme`, but our inline styles use `color: #95a5a6` literals that break in both modes. The user's homelab apps (Karakeep, Immich, Vaultwarden, Paperless, Grafana, PocketID) all default to dark.
6. **Polling-only, no streaming.** Every host row re-renders every 5 s for every connected dashboard tab. With 50 hosts × 3 metrics × 5 s polls this is fine, but with 500 hosts (or 10 concurrent operator tabs) the database pressure becomes silly. There is no SSE / WebSocket path.
7. **uPlot rendering is brittle.** The IIFE is loaded at the end of `<body>`, sparklines render in a `setTimeout(0)` after fetch — race conditions on slow networks leave empty charts. No retry, no loading state, no error state.
8. **No design system.** Colors, spacing, typography, iconography are all ad-hoc. There are no reusable components, no tokens, no theme. Each new feature reinvents its own pattern.
9. **No accessibility.** Tables have `role="grid"` and that's it. No keyboard navigation between rows, no focus management on modal partials, no skip links, no ARIA labels on the live-updating regions.
10. **No state persistence.** Group filter is in the URL but the dropdown does a full `window.location.href = ...` reload. Sort order, expanded row, time-window selection — all lost on every poll.
11. **No streaming logs / terminal.** Command results are fetched as JSON; there is no live `xterm.js` view, no log tail.

### 1.3 Why the v1.0 stack cannot stretch to the v1.5 goals

The user's stated goal (this ADR) is a "proper web UI" matching the polish of the rest of the homelab. The Jinja+HTMX+Pico stack can be polished — Tailwind, Alpine.js, vendored deps, design tokens, components-as-macros all work. But:

- The features that need to land next quarter (real-time streaming terminal, command palette, host-detail page with rich time-series charts, approval queue with live updates, settings UI for users/groups/ACLs, multi-step enroll wizard) push past what HTMX swaps comfortably. Each new interactive piece becomes a special-case `<script>` tag.
- The homelab stack is overwhelmingly SvelteKit (PocketID, Karakeep, Immich, Just-Eat tracker UI, Stash) — keeping FastAPI + Jinja means Ramón maintains two frontend mental models. SvelteKit is the path of least cognitive load.
- The agent is FOSS (`monxas/remote-pulse`); the server (and therefore the dashboard) is also OSS-able. A SvelteKit + JSON API split is a much more attractive on-ramp for external contributors than "Jinja2 + Pico".

### 1.4 What is *not* changing

This ADR is **frontend-only**. Out of scope:

- The agent protocol (heartbeat / command / approval shapes).
- The Postgres + TimescaleDB schema (F1).
- The Tailscale + tsnet networking model (F2).
- The PocketID OIDC IdP integration (F5 — auth flow stays as in ADR-0008 + the bug-fix session shipped 2026-05-25).
- Approvals via Telegram, Grafana dashboards, Prometheus exporter (F7/F8).

What changes: the rendering layer (`server/src/rp_server/templates/` and the routes in `server/src/rp_server/routers/web.py`), the static-asset pipeline, and the JSON API endpoints (some need to be added — `/v1/dash/*` — to back the new pages).

---

## 2. Decision Drivers

Priority descending.

1. **Match the homelab aesthetic.** Dark-mode-first, dense data, monospace for IDs/hostnames, Lucide icons, radix-color palette. The dashboard should feel like a sibling to Karakeep / Immich, not like a different product.
2. **Mobile-first.** Family Hub tablet (1080p portrait) and Ramón's phone are real consumption surfaces. Touch targets ≥44 px, gesture-friendly modals, no hover-only affordances.
3. **Real-time-capable.** The architecture must support SSE or WebSocket streaming for fleet state changes, command output, log tails — even if v1.1 ships with polling.
4. **Component-driven.** Buttons, inputs, tables, cards, dialogs, toasts, badges, charts must all be reusable typed components with a single source of truth for tokens.
5. **Accessibility AA.** WCAG 2.1 AA: keyboard navigation, focus traps in dialogs, ARIA live regions for fleet updates, prefers-reduced-motion respected, color contrast ≥4.5:1.
6. **Build pipeline that fits the project.** No node runtime requirement on the server. Static assets pre-built at CI time and served by FastAPI's `StaticFiles`. Source code in a `web/` sibling directory, built via `npm run build`, output checked in OR rebuilt in CI.
7. **API-first.** Every page consumes the same JSON API that the CLI/TUI/external integrators can consume. No template-only data shapes. OpenAPI schema is the contract.
8. **Maintainable by one person.** Ramón is the only operator. The stack must be boring, well-documented, and have a fast feedback loop (HMR < 200 ms, full rebuild < 10 s).
9. **OSS-friendly.** All deps Apache-2.0 / MIT / BSD. No proprietary fonts (use Geist / Inter via Fontsource), no copyleft.
10. **Backwards-compatible with v1.0.0 endpoints.** The new SPA consumes the existing `/v1/hosts`, `/v1/commands`, etc. APIs. Endpoint additions (e.g. `/v1/dash/overview`, `/v1/dash/host/:id/timeseries`) follow API-compat policy (additive only).

---

## 3. Considered Options

### 3.1 Rendering architecture

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| **SvelteKit SPA (static) + FastAPI JSON API** | Matches homelab stack, smallest bundle of the SPA options (~80 kB gzip), Vite HMR, file-based routing, first-class TypeScript, shadcn-svelte ecosystem mature, `adapter-static` produces a folder you can serve from `StaticFiles`. | New build pipeline. Requires node 22 in CI. The server now has two source trees. | ✅ **Chosen** |
| HTMX + Alpine.js + Tailwind (server-rendered) | No build pipeline at runtime (Tailwind CLI builds CSS once). Keeps Jinja templates. Smaller LOC delta. | Hits ceilings on interactivity (streaming terminal, command palette, multi-step wizard). Forces a second frontend mental model alongside the rest of the homelab. | ❌ Rejected — ceiling too low for v1.5 goals. |
| Next.js + React | Largest ecosystem, more candidates if we ever need contractors. | Doesn't match homelab. Bigger bundle (~250 kB+ vs ~80 kB for Svelte). React boilerplate for what is fundamentally a CRUD-with-charts app. | ❌ Rejected — no homelab fit. |
| Solid.js / Qwik | Smaller bundles than React, fine-grained reactivity. | Smaller ecosystems than Svelte. shadcn equivalents less mature. No homelab precedent. | ❌ Rejected — no homelab fit. |
| Astro + islands | Best for content-heavy pages, lazy hydration. | Dashboards are not islands — every cell is interactive. Astro shines for the wrong axis. | ❌ Rejected — wrong tool for the job. |

**Decision:** SvelteKit (SvelteKit 2, Svelte 5 with runes), `@sveltejs/adapter-static`, output to `web/build/` then copied into `server/src/rp_server/static/dash/`. FastAPI mounts that path as `/dash/`. All page transitions are client-side after first load; first-load HTML is the empty SPA shell with a `<script type="module">` entrypoint.

### 3.2 Design system

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| **Tailwind v4 + shadcn-svelte + radix-colors tokens** | shadcn-svelte (the Svelte port of shadcn/ui) ships copy-paste accessible components built on Bits UI primitives. Tailwind v4 has CSS-first config, no PostCSS. radix-colors gives 12-step ramps that work in light/dark. | shadcn-svelte is a "copy into your repo" pattern, not an npm dep — you own the components forever. | ✅ **Chosen** |
| Skeleton UI (Svelte-native) | Single npm install, Svelte-first. | Less mature than shadcn-svelte. Smaller component palette. Less control over individual components. | ❌ Rejected — less ownership of components. |
| Flowbite Svelte | Polished components, batteries-included. | Tailwind v3, hasn't shipped v4 support yet. Less customizable than copy-paste. | ❌ Rejected — Tailwind version drag. |
| Headless UI + custom design | Maximum control. | Reinventing every component. Months of work before any page is done. | ❌ Rejected — too slow. |

**Decision:** Tailwind v4 + shadcn-svelte components (copy-pasted into `web/src/lib/components/ui/`) + `@radix-ui/colors` tokens exported as CSS variables. Bits UI is the underlying primitive set.

### 3.3 State management & data fetching

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| **TanStack Query (svelte-query)** | Caching, refetch on focus/window/network, stale-while-revalidate, optimistic updates, devtools. Pairs naturally with SSE/WebSocket invalidation. | Adds ~14 kB. | ✅ **Chosen** |
| Svelte stores only | Zero deps. | Hand-rolled cache, hand-rolled refetch, hand-rolled retry. Not worth it past 3 pages. | ❌ Rejected — too much bespoke code. |
| SvelteKit's `+page.server.ts` load functions | First-party. | Server-side load is wrong here — we are a static SPA, not SSR. | ❌ Rejected — wrong shape. |

**Decision:** `@tanstack/svelte-query` with a global QueryClient. Mutations for command issuance, approval actions, settings changes. SSE subscriptions invalidate relevant query keys on push.

### 3.4 Real-time transport

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| **Server-Sent Events (SSE) over `/v1/dash/stream`** | One-way is exactly what we need (server pushes fleet updates to clients). Works through Caddy without WebSocket upgrade. Auto-reconnect built into `EventSource`. Plays well with HTTP/2 multiplexing. | Browser limit of 6 SSE per origin per HTTP/1.1 — not a problem under HTTP/2 which Caddy already speaks. | ✅ **Chosen** |
| WebSocket | Bidirectional. | We don't need bidirectional — commands go through normal POST. WS adds reconnection logic complexity and Caddy upgrade config. | ❌ Rejected — overkill for unidirectional. |
| Long-polling | Simplest. | Worst of all worlds: latency of polling + complexity of streaming. | ❌ Rejected. |
| Polling only (status quo) | Already shipped. | Doesn't meet driver #3. | ❌ Rejected — keep for fallback only. |

**Decision:** SSE endpoint `GET /v1/dash/stream` emits `host.heartbeat`, `host.status_change`, `command.status_change`, `approval.created` events. svelte-query subscribes via `EventSource`, invalidates relevant cache keys on event. Polling stays as fallback when SSE fails (e.g. corporate proxies that buffer).

### 3.5 Charts

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| **uPlot (keep)** | Fastest time-series renderer in the browser (~40 kB, sub-millisecond redraws). Already in the v1.0 stack. Suits sparklines and detail charts. | Imperative API — needs a small Svelte wrapper. No declarative React-style props. | ✅ **Chosen** |
| Apache ECharts | Beautiful out of the box, declarative options. | ~350 kB gzip. Overkill for our chart types. | ❌ Rejected — bundle cost. |
| Recharts / Chart.js | Familiar API. | Slower at high cardinality. Larger bundles than uPlot. | ❌ Rejected — perf + bundle. |
| D3 from scratch | Total control. | Months of work. | ❌ Rejected — too slow. |

**Decision:** keep uPlot. Wrap in a `<Sparkline>` and `<TimeseriesChart>` Svelte component with reactive props.

### 3.6 Icons

| Option | Verdict |
|--------|---------|
| **Lucide (`lucide-svelte`)** — ✅ Open license, ~1500 icons, tree-shakeable, the de-facto shadcn icon set. |
| Heroicons — ❌ smaller set. |
| Iconify — ❌ powerful but over-broad for our needs. |

### 3.7 Typography

- **Inter** (variable) for UI text — via `@fontsource-variable/inter`, self-hosted, no CDN.
- **Geist Mono** (variable) for hostnames, IDs, command output, sparkline axis labels — via `@fontsource-variable/geist-mono`.
- No Google Fonts CDN (driver #6, driver #9, and the CSP problem from §1.2).

### 3.8 Build & deploy

| Question | Decision |
|----------|----------|
| Where does the source live? | `web/` at the repo root, sibling to `server/` and `agent/`. |
| What is the build output? | `web/build/` (SvelteKit static adapter). Copied by `scripts/build_dashboard.sh` to `server/src/rp_server/static/dash/`. |
| Is the build output committed? | **No.** CI builds and packages it into the wheel via `hatch-build-scripts`. Local dev rebuilds via `npm run build` or runs the Vite dev server on `:5173` with a proxy to `localhost:8080/v1/*`. |
| Node version? | Node 22 LTS (current LTS at time of writing). Pinned via `.nvmrc` and `engines` in `package.json`. |
| Lockfile? | `package-lock.json` (npm) — matches the rest of monxas tooling (no pnpm/yarn migration overhead). |
| How does FastAPI serve it? | `app.mount("/dash", StaticFiles(directory=..., html=True))` with a catch-all rewrite to `index.html` for client-side routing. Auth gate (`current_user_optional → redirect to /auth/login`) wraps the mount via a middleware. |
| Cache headers? | `Cache-Control: public, max-age=31536000, immutable` for hashed assets (`/dash/_app/*`). `Cache-Control: no-cache` for `index.html`. |

### 3.9 Auth in the SPA

The OIDC session cookie (`rp_session`) shipped in the 2026-05-25 bugfix already covers SPA needs:

- SPA boot: fetch `/auth/me` → if 200 + `authenticated: true`, render shell; if 401, redirect to `/auth/login?next=<current-path>`.
- Cookie is `HttpOnly` + `SameSite=Lax` + `Secure` — JS never touches it, XSS cannot exfiltrate it. CSRF protection comes from `SameSite=Lax` for safe methods + an `X-Requested-With: XMLHttpRequest` check on mutations (added in this ADR).
- Logout: `POST /auth/logout` → 302 → `/auth/login` (handled at the app level by tanstack-query's mutation success handler).
- Role-aware UI: `/auth/me` returns `{ user_id, email, role, accessible_groups }`. The SPA hides admin-only nav items at the client (server still enforces).

---

## 4. Decision (TL;DR)

Build a SvelteKit static SPA in `web/`, served by FastAPI under `/dash/`, consuming a stable JSON API under `/v1/`. Tailwind v4 + shadcn-svelte + radix-colors + Lucide + Geist Mono. SSE for real-time, TanStack Query for cache, uPlot for charts, OIDC session cookie for auth. Dark mode default, mobile-first, WCAG 2.1 AA.

Ship in five phases (§7). v1.0.0 GA dashboard remains untouched during phase 0–2 (parallel `/dash-next/` URL); cutover at phase 3.

---

## 5. Information Architecture

### 5.1 Sitemap

```
/dash/                          Shell (SvelteKit root layout)
├── /                           Fleet overview      ← landing
├── /hosts                      Host list (filterable, searchable)
├── /hosts/:id                  Host detail
│   ├── /metrics                Time-series charts (CPU, RAM, disk, net, load)
│   ├── /commands               Commands issued to this host
│   ├── /logs                   Live agent log tail (SSE)
│   └── /keys                   SSH keys registered for this host
├── /commands                   Global command center
│   ├── /                       Issue + history
│   └── /:id                    Command detail (output, approvals, audit)
├── /approvals                  Pending approvals queue
├── /audit                      Audit log timeline
├── /enroll                     Host onboarding wizard (multi-step)
└── /settings
    ├── /profile                Current user (email, theme, tokens)
    ├── /users                  Admin: users CRUD
    ├── /groups                 Admin: groups + ACLs
    └── /integrations           Admin: Telegram, Tailscale ACL, PocketID, n8n
```

### 5.2 Top-level navigation

```
┌──────────────────────────────────────────────────────────────────────┐
│ ⏚ Remote-Pulse    Fleet  Hosts  Commands  Approvals  Audit  Enroll   │
│                                                          🔔 3   RK ▾ │
└──────────────────────────────────────────────────────────────────────┘
```

- Logo + product name on the left.
- Primary nav: 6 items, role-filtered (viewer sees Fleet/Hosts/Audit only, operator adds Commands, admin adds Approvals/Enroll/Settings).
- Right side: notifications bell (badge = pending approvals + recent command failures), user avatar with dropdown (theme, profile, logout).
- Mobile: nav collapses to a hamburger; right-side bell + avatar stay visible.

### 5.3 Page-by-page wireframes (ASCII)

#### Fleet overview (`/`)

```
┌──────────────────────────────────────────────────────────────────────┐
│ Fleet                                              ⟳ live   ▼ all   │
├──────────────────────────────────────────────────────────────────────┤
│ ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐         │
│ │ Total      │ │ Online     │ │ Stale      │ │ Pending    │         │
│ │   42       │ │   38       │ │   3        │ │  approvals │         │
│ │            │ │ 90% ▲      │ │ 7% ▼       │ │   2        │         │
│ └────────────┘ └────────────┘ └────────────┘ └────────────┘         │
│                                                                       │
│ Search ⌕ [_______________]   Group ▾ [all]   Status ▾ [all]          │
│                                                                       │
│ ┌──────────────────────────────────────────────────────────────────┐ │
│ │ Hostname        Group   Status   CPU      RAM      Net    Seen   │ │
│ ├──────────────────────────────────────────────────────────────────┤ │
│ │ pmx-50          prod    ● live  ▁▂▃▅█  ▁▁▂▂▂▃  ▁▂  3s         │ │
│ │ pmx-51          prod    ● live  ▁▁▁▂▂  ▁▂▂▂▂   ▁   5s         │ │
│ │ media-208       prod    ● live  ▂▃▅█▇  ▃▃▃▃▃▃  ▅▅  2s         │ │
│ │ carmelo-mini    extern  ◐ stale ▁▁▁?? ▂▂▂??   ?   2m          │ │
│ │ rp-server       prod    ● live  ▁▁▂▂▂  ▁▁▁▁▁   ▁   1s         │ │
│ │ ...                                                              │ │
│ └──────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

- 4 stat cards across the top: Total, Online, Stale, Pending approvals.
- Filter row: text search (debounced 200 ms), group dropdown, status dropdown.
- Host table with inline sparklines (60-point rolling, 5 min window).
- Row click → `/hosts/:id`.
- Live region: a `aria-live="polite"` announces "Host X went stale" / "Host Y came back" for screen readers.

#### Host detail (`/hosts/:id`)

```
┌──────────────────────────────────────────────────────────────────────┐
│ ← Back to fleet                                                       │
│                                                                       │
│ pmx-50.monxas.casa                                  [Issue command ▾] │
│ prod · Ryzen 5 5600G · Proxmox 8.5 · 64 GB · Online (3s ago)         │
│                                                                       │
│ Tabs:  [Metrics] [Commands] [Logs] [Keys]                            │
├──────────────────────────────────────────────────────────────────────┤
│ Window: [1h ▾]    Series: ☑ CPU ☑ RAM ☑ Load ☐ Net ☐ Disk           │
│                                                                       │
│ ┌──────────────────────────────────────────────────────────────────┐ │
│ │ CPU %                                                            │ │
│ │  100 ┤                                                           │ │
│ │   50 ┤    ╭╮  ╭─╮     ╭───╮                                      │ │
│ │    0 ┴────╯╰──╯ ╰─────╯   ╰──────────────────────────────────    │ │
│ │      12:00     12:15     12:30     12:45     13:00              │ │
│ └──────────────────────────────────────────────────────────────────┘ │
│ ┌──────────────────────────────────────────────────────────────────┐ │
│ │ RAM %                                                            │ │
│ │  ... (uPlot chart)                                               │ │
│ └──────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

- Top: breadcrumb + hostname + facts (group, hardware, OS, last-seen).
- Action: "Issue command" splits into [Run shell], [Exec script], [Push key], [Reboot] menu.
- Tabs for Metrics / Commands / Logs / Keys.
- Charts: full-size uPlot, brushable, with crosshair tooltip.

#### Commands (`/commands`)

```
┌──────────────────────────────────────────────────────────────────────┐
│ Commands                                              [+ New command] │
├──────────────────────────────────────────────────────────────────────┤
│ Filter: status ▾  host ▾  issued-by ▾  date-range ▾                  │
│                                                                       │
│ ┌──────────────────────────────────────────────────────────────────┐ │
│ │ ⏵ ⏳ #cmd-93f2  uname -a               pmx-50    pending-approval │ │
│ │ ⏵ ✓ #cmd-93f1  ssh-rotate              media-208  succeeded 5m   │ │
│ │ ⏵ ✗ #cmd-93f0  apt update              carmelo    timeout 1h     │ │
│ └──────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

- Click a row to expand inline (no navigation) — shows output, approval chain, retry button.
- "+ New command" opens a dialog with host multi-select, command type, parameters, dry-run toggle.

#### Approvals (`/approvals`)

```
┌──────────────────────────────────────────────────────────────────────┐
│ Pending approvals (2)                                                 │
├──────────────────────────────────────────────────────────────────────┤
│ ┌──────────────────────────────────────────────────────────────────┐ │
│ │ #cmd-93f2  reboot                       pmx-50                   │ │
│ │ Requested by ramonkawa@gmail.com · 2 min ago                     │ │
│ │ Reason: "kernel update"                                          │ │
│ │                                              [Reject]  [Approve] │ │
│ └──────────────────────────────────────────────────────────────────┘ │
│ ┌──────────────────────────────────────────────────────────────────┐ │
│ │ #cmd-93f3  ssh-rotate                   carmelo                  │ │
│ │ ...                                          [Reject]  [Approve] │ │
│ └──────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

- Approve / reject calls the existing `/v1/approvals/:id/approve|reject` endpoints (same as Telegram bot path).
- Optimistic UI: card slides out on click, error → snaps back + toast.

#### Audit (`/audit`)

```
┌──────────────────────────────────────────────────────────────────────┐
│ Audit log                                                             │
├──────────────────────────────────────────────────────────────────────┤
│ Filter: actor ▾  action ▾  target ▾  date-range ▾                    │
│                                                                       │
│  ●  13:42:18  ramon  approved cmd-93f2 on pmx-50                     │
│  │                                                                    │
│  ●  13:42:01  ramon  issued cmd-93f2 (reboot) on pmx-50              │
│  │                                                                    │
│  ●  13:40:30  system  marked carmelo-mini as stale (90s no heartbeat)│
│  │                                                                    │
│  ●  13:35:12  ramon  enrolled rp-test-vm in group:dev                │
│  │                                                                    │
│  ●  13:30:00  system  command cmd-93f0 timed out on carmelo-mini    │
│  ●                                                                    │
└──────────────────────────────────────────────────────────────────────┘
```

- Vertical timeline, infinite scroll, cursor-based pagination.
- Each row links to the relevant resource (host, command, user).

#### Enroll wizard (`/enroll`)

Multi-step:

1. **Choose OS** — Linux / macOS / Windows pills.
2. **Choose group** — dropdown of existing groups or "create new".
3. **Generate enrollment token** — calls `/v1/enrollment-links/new`, shows the curl-pipe-sh one-liner with the token baked in, plus a QR code for mobile installs.
4. **Wait for first heartbeat** — page polls `/v1/hosts?enrolled_after=<ts>` and shows a green check when the host appears. Auto-redirects to the new host's detail page.

#### Settings

- **Profile**: theme (system / light / dark), notification preferences, list of personal API tokens with "revoke".
- **Users** (admin): table of users + role + groups + last-login. Edit dialog.
- **Groups** (admin): list of groups + member count + ACL summary. Edit groups + add Tailscale ACL tags.
- **Integrations** (admin): toggle + configure Telegram bot, PocketID, n8n approval webhook.

---

## 6. Design system specification

### 6.1 Color tokens (radix-colors mapped to CSS variables)

```css
/* web/src/lib/styles/tokens.css */

:root[data-theme="dark"] {
  --bg-base:        var(--slate-1);    /* near-black */
  --bg-subtle:      var(--slate-2);
  --bg-elevated:    var(--slate-3);    /* cards */
  --bg-hover:       var(--slate-4);
  --border-subtle:  var(--slate-6);
  --border-default: var(--slate-7);
  --text-muted:     var(--slate-11);
  --text-default:   var(--slate-12);

  --accent-bg:      var(--blue-3);
  --accent-solid:   var(--blue-9);     /* primary buttons */
  --accent-text:    var(--blue-11);

  --success-solid:  var(--green-9);
  --warn-solid:     var(--amber-9);
  --danger-solid:   var(--red-9);
}

:root[data-theme="light"] {
  /* same names, mapped to whiteAlpha equivalents */
}
```

Status colors:

- **online** → green-9
- **stale** → amber-9 (heartbeat 60–180 s ago)
- **offline** → red-9 (>180 s)
- **unknown** → slate-9

### 6.2 Typography scale

| Token | Family | Size | Weight | Use |
|-------|--------|------|--------|-----|
| `--text-xs` | Inter | 12 px / 16 lh | 400 | secondary metadata |
| `--text-sm` | Inter | 13 px / 18 lh | 400 | table cells, body |
| `--text-base` | Inter | 14 px / 20 lh | 400 | body |
| `--text-lg` | Inter | 16 px / 24 lh | 500 | section headers |
| `--text-xl` | Inter | 20 px / 28 lh | 600 | page titles |
| `--text-2xl` | Inter | 24 px / 32 lh | 700 | hero stats |
| `--font-mono` | Geist Mono | inherit | 400 | IDs, hostnames, log output, sparkline ticks |

### 6.3 Spacing

4-px base grid. Tailwind spacing scale (`p-1` = 4 px, `p-2` = 8 px, …) unchanged.

### 6.4 Radius

| Token | Value | Use |
|-------|-------|-----|
| `--radius-sm` | 4 px | inputs, small badges |
| `--radius-md` | 6 px | buttons |
| `--radius-lg` | 8 px | cards |
| `--radius-xl` | 12 px | dialogs |
| `--radius-full` | 9999 px | avatars, pills |

### 6.5 Motion

- All transitions ≤200 ms.
- `prefers-reduced-motion: reduce` disables non-essential motion (fades, slides). Charts still update; only ornamental motion is killed.
- Loading skeletons (Bits UI `Skeleton`) for any data fetch ≥150 ms.

### 6.6 Component inventory (initial)

shadcn-svelte components to scaffold in `web/src/lib/components/ui/`:

`button`, `input`, `label`, `select`, `checkbox`, `radio-group`, `switch`, `textarea`, `dialog`, `sheet` (mobile drawer), `dropdown-menu`, `command` (cmd-k palette), `tabs`, `table`, `card`, `badge`, `avatar`, `toast` (sonner-svelte), `tooltip`, `popover`, `skeleton`, `separator`, `progress`, `breadcrumb`, `pagination`, `alert`, `alert-dialog`.

App-specific components in `web/src/lib/components/app/`:

`HostStatusBadge`, `Sparkline` (uPlot wrapper), `TimeseriesChart`, `HostTable`, `CommandRow`, `ApprovalCard`, `AuditEvent`, `EnrollWizard`, `OnboardCurlSnippet`, `LiveRegion`, `ThemeToggle`, `CommandPalette` (Cmd-K).

---

## 7. Migration plan (phased)

Each phase is independently shippable. v1.0.0 dashboard stays live until phase 3 cutover.

### Phase 0 — Foundations (1 week)

- `web/` scaffold: SvelteKit 2, Svelte 5 runes, Tailwind v4, tsconfig strict, ESLint + Prettier configs, Vitest.
- shadcn-svelte init, copy in: `button`, `input`, `card`, `table`, `dialog`, `tabs`, `toast`.
- Token files: `tokens.css`, `theme.ts`.
- Build pipeline: `npm run build` → `web/build/` → `scripts/build_dashboard.sh` copies to `server/src/rp_server/static/dash/`.
- CI: `web-ci.yml` runs lint, unit, build on every PR.
- FastAPI: mount `/dash-next/` (parallel to existing `/dash/`).
- Auth: SPA boots, hits `/auth/me`, redirects to `/auth/login` if needed.
- **Exit criteria:** `https://rp.monxas.casa/dash-next/` loads a "Hello fleet" page with dark mode, requires login, builds in CI.

### Phase 1 — Fleet overview + Host detail (2 weeks)

- JSON API: `GET /v1/dash/overview` (stat cards) — additive.
- JSON API: `GET /v1/dash/hosts` enriched with sparkline buffers — additive.
- JSON API: `GET /v1/dash/hosts/:id/timeseries?window=&series=` — additive (existing `/dash/host/:id/sparkline-data` is the seed).
- Pages: `/`, `/hosts`, `/hosts/:id` (metrics tab only).
- Components: `HostStatusBadge`, `Sparkline`, `TimeseriesChart`, `HostTable`.
- SSE endpoint: `GET /v1/dash/stream` emits `host.heartbeat`, `host.status_change`.
- **Exit criteria:** the v1.0 dashboard's read-only feature parity, with dark mode, mobile layout, live updates.

### Phase 2 — Commands + Approvals + Audit (2 weeks)

- Pages: `/commands`, `/commands/:id`, `/approvals`, `/audit`.
- JSON API additions: cursor-paginated audit log, command issuance via SPA, approval action endpoints (already exist — wire up).
- SSE additions: `command.status_change`, `approval.created`, `approval.resolved`.
- Components: `CommandRow`, `ApprovalCard`, `AuditEvent`, `CommandPalette`.
- **Exit criteria:** operator can issue, watch, and approve a command end-to-end without touching the CLI/TUI/Telegram.

### Phase 3 — Cutover (0.5 week)

- Redirect `/dash/` → `/dash-next/`.
- Rename `/dash-next/` → `/dash/`.
- Mark v1.0 Jinja templates and `web.py` route handlers as deprecated. Keep the JSON sparkline endpoint live for a release cycle.
- Update docs.

### Phase 4 — Enroll wizard + Settings (1.5 weeks)

- Pages: `/enroll`, `/settings/*`.
- JSON API additions: `/v1/enrollment-links` already exists (F7-6) — wire up; admin endpoints for users/groups/ACLs may need new write paths.
- Components: `EnrollWizard`, settings forms.
- **Exit criteria:** admin can onboard a host and edit users/groups/ACLs entirely from the web.

### Phase 5 — Polish & accessibility audit (1 week) — **in progress**

- Full WCAG 2.1 AA pass (axe-core CI gate).
- Performance budget: first paint ≤1 s on 3G, Lighthouse score ≥90 in all categories.
- E2E tests (Playwright) for: login flow, issue command, approve command, enroll host.
- Storybook (Histoire for Svelte) for component docs.
- **Exit criteria:** v1.5 release, ADR moves to **Accepted**.

Progress (2026-05-26):

- [x] axe-core CI gate (baseline mode, `.github/workflows/a11y.yml` + `web/tests/e2e/a11y.spec.ts`, 2026-05-26)
- [x] Lighthouse CI workflow (warn-only baseline, `.github/workflows/lighthouse.yml` + `web/lighthouserc.json`)
- [ ] Lighthouse ≥90 perf/a11y/best-practices score (today: warn-only, baseline not yet measured in CI)
- [ ] axe-core 0 critical violations (currently: baseline-N — see `web/tests/a11y-baseline/`)
- [ ] Playwright E2E full coverage (login, issue command, approve, enroll)
- [ ] Storybook / Histoire component catalog

**Total: ~7 weeks calendar (one person, part-time).** Faster if parallelized via sub-agents (cf. ADR-0008 same-day execution playbook).

---

## 8. API contract changes

All additive, namespaced under `/v1/dash/` to keep the existing public agent API (`/v1/heartbeat`, `/v1/commands`, …) unchanged.

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v1/dash/overview` | GET | Stat cards (total/online/stale/pending). |
| `/v1/dash/hosts` | GET | Host list with embedded short sparkline buffer (~60 points). |
| `/v1/dash/hosts/:id/timeseries` | GET | Time-series for one host (multi-series, multi-window). |
| `/v1/dash/audit` | GET | Cursor-paginated audit log. |
| `/v1/dash/stream` | GET (SSE) | Live event stream. |
| `/v1/dash/me` | GET | Same shape as `/auth/me` but namespaced for the SPA. |

The SPA never calls the existing `/v1/heartbeat` (write) or `/v1/enroll` (agent-only) endpoints.

OpenAPI: `make openapi-check` (already in CI) catches breaking changes.

---

## 9. Open questions

1. **Storage of theme preference.** Cookie vs `localStorage`? Decision: `localStorage` for the SPA (no server round-trip), cookie only if we ever SSR a public page.
2. **Cmd-K palette scope.** Phase 2 ships search-only (jump to host/command/page). Future phases may add command issuance from the palette.
3. **i18n.** Spanish + English. Defer to phase 5+. Keep all strings in `web/src/lib/i18n/en.ts` from day one so adding `es.ts` is mechanical.
4. **Mobile push notifications.** PWA install + Web Push for approval alerts? Defer to a follow-on ADR — Telegram already covers this.
5. **Embedded TUI?** xterm.js for `/hosts/:id/logs` is in scope (phase 1.5 or 2). xterm.js for `/hosts/:id/shell` (interactive SSH-over-Tailscale via WebSocket) is **out of scope** — that needs its own ADR with security review.
6. **Multi-tenant theming.** Different orgs / customers branding the dashboard? Out of scope for v1.x; revisit if hosted-service path opens.

---

## 10. Acceptance criteria

The redesign is **Accepted** when:

- ✅ All 7 pages from §5.1 are reachable, role-gated correctly, mobile-responsive.
- ✅ Lighthouse score ≥90 on /dash (performance, accessibility, best-practices, SEO=N/A).
- ✅ axe-core CI gate green (0 violations).
- ✅ Playwright E2E flows green: login, fleet view, issue+approve command, enroll host.
- ✅ Bundle size ≤200 kB gzip first-load JS.
- ✅ SSE reconnect tested (network blip, server restart).
- ✅ Dark mode + light mode visually QA'd.
- ✅ Old `/dash/` Jinja routes return 410 Gone (post-cutover, with `Link: </dash/>; rel="canonical"`).
- ✅ Docs updated: `docs/docs/architecture/components.md`, `docs/docs/guide/dashboard.md`, this ADR moved to **Accepted**.

---

## 11. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Scope creep beyond 7 weeks | Medium | Medium | Strict phase gates; new feature ideas → backlog, not in-phase. |
| SSE reliability through corporate proxies | Low | Low | Polling fallback already in TanStack Query. |
| shadcn-svelte component churn | Low | Low | Pinned via lockfile; we own the copies. |
| Tailwind v4 stability (still relatively new) | Low | Medium | Pin to a known-good minor; defer upgrades to phase 5. |
| Loss of v1.0 audit log compatibility during cutover | Low | High | Old endpoints stay live for a release cycle; cutover is a redirect, not a schema change. |
| Node 22 dep on CI | Low | Low | GitHub Actions `setup-node@v4` covers it; same node version used in homelab tooling already. |
| OIDC session length too short for SPA UX | Medium | Low | Currently 12 h. Bump to 24 h + silent re-auth via `/auth/refresh` (defer to phase 1 if needed). |

---

## 12. Future work (post-v1.5)

- Interactive SSH-over-Tailscale terminal (own ADR).
- Mobile PWA install + Web Push approvals.
- Multi-tenant theming.
- Operator runbooks embedded in `/hosts/:id` (markdown viewer).
- Inline Grafana panels on `/hosts/:id/metrics` (iframe with CF Access auth pass-through).
- Bulk operations UI (issue command to N hosts, fleet-wide ssh-key rotation).

---

## 13. References

- ADR-0008 §F5 — original Jinja+HTMX+Pico dashboard.
- ADR-0008 §F7 — magic-link enrollment (backs the Enroll wizard).
- SvelteKit 2 docs — <https://kit.svelte.dev>
- shadcn-svelte — <https://www.shadcn-svelte.com>
- Tailwind v4 — <https://tailwindcss.com>
- Radix Colors — <https://www.radix-ui.com/colors>
- TanStack Query (Svelte) — <https://tanstack.com/query/latest/docs/svelte/overview>
- uPlot — <https://github.com/leeoniya/uPlot>
- Lucide icons — <https://lucide.dev>
- Geist Mono / Inter via Fontsource — <https://fontsource.org>
- WCAG 2.1 AA — <https://www.w3.org/WAI/WCAG21/quickref/?levels=aaa>
