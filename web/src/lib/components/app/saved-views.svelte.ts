/**
 * Saved views — named presets for filter combinations across pages.
 *
 * Promotes the URL-state model used by sortable tables + audit filters
 * into reusable, named bookmarks. Per-scope persistence in localStorage
 * (key `rp:saved-views:<scope>`); factory views ship as non-deletable
 * defaults so the switcher is useful before the operator saves anything.
 *
 * The store is split into:
 *   - Pure helpers (serialize/deserialize/compare params, slugify) — unit
 *     testable without a DOM.
 *   - A rune-backed `createSavedViewsStore` factory used by the component.
 *
 * Each scope (`fleet`, `audit`, `commands`, …) owns its own list. Factory
 * views live in code (see {@link FACTORY_VIEWS}) so they survive cache
 * wipes and can't be deleted by mistake.
 */
import { page } from '$app/state';
import { goto } from '$app/navigation';
import { SvelteDate, SvelteSet, SvelteURLSearchParams } from 'svelte/reactivity';

/** Serializable representation of URL search params for a saved view. */
export type ViewParams = Record<string, string | string[]>;

export interface SavedView {
  /** Stable id (`factory:<slug>` for built-ins, uuid-ish for user views). */
  id: string;
  /** Display name. Unique per scope (case-insensitive). */
  name: string;
  /** Page scope, e.g. `fleet`, `audit`, `commands`. */
  scope: string;
  /** Serialized URL params (key → string | string[]). */
  params: ViewParams;
  /** ISO timestamp (UTC) when the view was created. */
  createdAt: string;
  /** When `true`, surfaced in the top row of the switcher. */
  pinned?: boolean;
  /** When `true`, view is built-in and non-deletable. */
  factory?: boolean;
}

const STORAGE_PREFIX = 'rp:saved-views';

export function storageKey(scope: string): string {
  return `${STORAGE_PREFIX}:${scope}`;
}

// ─── Pure helpers ──────────────────────────────────────────────────────────

/**
 * Normalize a URLSearchParams-like into the {@link ViewParams} shape used
 * for persistence. Single values become strings; repeated keys become
 * sorted arrays so equality compares cleanly later.
 */
export function paramsFromUrl(sp: URLSearchParams): ViewParams {
  const out: ViewParams = {};
  // Collect all values per key so repeated params (action=…&action=…) survive.
  const keys = new SvelteSet<string>();
  sp.forEach((_, k) => keys.add(k));
  for (const k of keys) {
    const all = sp.getAll(k);
    if (all.length === 0) continue;
    out[k] = all.length === 1 ? all[0]! : [...all].sort();
  }
  return out;
}

/** Returns true when two {@link ViewParams} are equivalent (order-insensitive). */
export function paramsEqual(a: ViewParams, b: ViewParams): boolean {
  const ka = Object.keys(a);
  const kb = Object.keys(b);
  if (ka.length !== kb.length) return false;
  for (const k of ka) {
    if (!(k in b)) return false;
    const av = a[k]!;
    const bv = b[k]!;
    if (Array.isArray(av) && Array.isArray(bv)) {
      if (av.length !== bv.length) return false;
      const sa = [...av].sort();
      const sb = [...bv].sort();
      for (let i = 0; i < sa.length; i++) if (sa[i] !== sb[i]) return false;
    } else if (Array.isArray(av) || Array.isArray(bv)) {
      // Mismatched shape — treat single-element array as scalar equality.
      const aArr = Array.isArray(av) ? av : [av];
      const bArr = Array.isArray(bv) ? bv : [bv];
      if (aArr.length !== bArr.length) return false;
      for (let i = 0; i < aArr.length; i++) if (aArr[i] !== bArr[i]) return false;
    } else {
      if (av !== bv) return false;
    }
  }
  return true;
}

/**
 * Render a {@link ViewParams} object into a search string (no leading `?`).
 * Stable ordering so URLs survive round-trips cleanly.
 */
export function paramsToSearch(params: ViewParams): string {
  const sp = new SvelteURLSearchParams();
  const keys = Object.keys(params).sort();
  for (const k of keys) {
    const v = params[k]!;
    if (Array.isArray(v)) for (const item of v) sp.append(k, item);
    else sp.set(k, v);
  }
  return sp.toString();
}

/** Slugify for factory-view ids. Lowercases + collapses non-alnum. */
export function slugify(input: string): string {
  return (
    input
      .normalize('NFKD')
      // Strip combining marks (accents) before lowercasing so "ó" → "o".
      .replace(/[̀-ͯ]/g, '')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/(^-|-$)+/g, '')
      .slice(0, 64)
  );
}

/** Generate a non-cryptographic id good enough for client-side keys. */
export function generateId(): string {
  // crypto.randomUUID is widely available; fall back for old browsers + tests.
  try {
    if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
      return crypto.randomUUID();
    }
  } catch {
    /* ignore */
  }
  return `v_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
}

// ─── Factory views (built-in, non-deletable) ───────────────────────────────

/**
 * Built-in factory views per scope. Surfaced in the switcher alongside
 * user-saved ones; tagged `factory: true` so the UI hides destructive
 * actions and `id` is stable across cache wipes.
 */
export const FACTORY_VIEWS: Record<string, ReadonlyArray<SavedView>> = {
  fleet: [
    {
      id: 'factory:all-hosts',
      name: 'All hosts',
      scope: 'fleet',
      params: {},
      createdAt: '1970-01-01T00:00:00.000Z',
      pinned: true,
      factory: true,
    },
    {
      id: 'factory:offline-only',
      name: 'Offline only',
      scope: 'fleet',
      params: { status: 'offline' },
      createdAt: '1970-01-01T00:00:00.000Z',
      pinned: true,
      factory: true,
    },
    {
      id: 'factory:prod-group',
      name: 'Production group',
      scope: 'fleet',
      params: { group: 'prod' },
      createdAt: '1970-01-01T00:00:00.000Z',
      factory: true,
    },
    {
      id: 'factory:family-group',
      name: 'Family group',
      scope: 'fleet',
      params: { group: 'family' },
      createdAt: '1970-01-01T00:00:00.000Z',
      factory: true,
    },
  ],
  audit: [
    {
      id: 'factory:today',
      name: 'Today',
      scope: 'audit',
      params: { range: '24h' },
      createdAt: '1970-01-01T00:00:00.000Z',
      pinned: true,
      factory: true,
    },
    {
      id: 'factory:last-7-days',
      name: 'Last 7 days',
      scope: 'audit',
      params: { range: '7d' },
      createdAt: '1970-01-01T00:00:00.000Z',
      pinned: true,
      factory: true,
    },
    {
      id: 'factory:settings-changes',
      name: 'Settings changes',
      scope: 'audit',
      params: { action_prefix: 'settings.' },
      createdAt: '1970-01-01T00:00:00.000Z',
      factory: true,
    },
    {
      id: 'factory:permission-grants',
      name: 'Permission grants',
      scope: 'audit',
      params: { action: ['settings.permission.grant', 'settings.permission.revoke'] },
      createdAt: '1970-01-01T00:00:00.000Z',
      factory: true,
    },
  ],
  commands: [
    {
      id: 'factory:all-commands',
      name: 'All commands',
      scope: 'commands',
      params: {},
      createdAt: '1970-01-01T00:00:00.000Z',
      pinned: true,
      factory: true,
    },
    {
      id: 'factory:pending-approval',
      name: 'Pending approval',
      scope: 'commands',
      params: { status: 'pending_approval' },
      createdAt: '1970-01-01T00:00:00.000Z',
      pinned: true,
      factory: true,
    },
    {
      id: 'factory:failed',
      name: 'Failed',
      scope: 'commands',
      params: { status: 'failed' },
      createdAt: '1970-01-01T00:00:00.000Z',
      factory: true,
    },
  ],
};

export function factoryViewsFor(scope: string): SavedView[] {
  return (FACTORY_VIEWS[scope] ?? []).map((v) => ({ ...v }));
}

// ─── localStorage I/O ──────────────────────────────────────────────────────

function safeStorage(): Storage | null {
  try {
    if (typeof window === 'undefined') return null;
    return window.localStorage;
  } catch {
    return null;
  }
}

export function loadUserViews(scope: string): SavedView[] {
  const ls = safeStorage();
  if (!ls) return [];
  try {
    const raw = ls.getItem(storageKey(scope));
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    // Drop anything that doesn't look like a saved view (forward-compat).
    return parsed.filter(
      (v): v is SavedView =>
        !!v &&
        typeof v === 'object' &&
        typeof (v as SavedView).id === 'string' &&
        typeof (v as SavedView).name === 'string' &&
        typeof (v as SavedView).scope === 'string' &&
        !(v as SavedView).factory,
    );
  } catch {
    return [];
  }
}

export function persistUserViews(scope: string, views: SavedView[]): void {
  const ls = safeStorage();
  if (!ls) return;
  try {
    // Only persist user-defined (non-factory) views.
    const filtered = views.filter((v) => !v.factory);
    ls.setItem(storageKey(scope), JSON.stringify(filtered));
  } catch {
    /* quota / disabled — silent fallback */
  }
}

// ─── CRUD result types ────────────────────────────────────────────────────

export type SaveResult =
  | { ok: true; view: SavedView }
  | { ok: false; error: 'name-required' | 'name-taken' };

// ─── Store factory ────────────────────────────────────────────────────────

export interface SavedViewsStore {
  /** Combined list (factory first, then user views). */
  readonly views: SavedView[];
  /** User-defined views only. */
  readonly userViews: SavedView[];
  /** Factory views only. */
  readonly factoryViews: SavedView[];
  /** Currently active view (matches URL params exactly), or null. */
  readonly active: SavedView | null;
  /** True when the URL params don't match any saved view. */
  readonly modified: boolean;
  /** Save current URL params as a new view with the given name. */
  saveCurrent(name: string, opts?: { pinned?: boolean }): SaveResult;
  /** Rename / pin / unpin an existing user view. */
  updateView(id: string, patch: Partial<Pick<SavedView, 'name' | 'pinned'>>): SaveResult;
  /** Delete a user view. Factory views can't be deleted. */
  deleteView(id: string): boolean;
  /** Apply the view's params to the URL (replaces current search). */
  applyView(view: SavedView): void;
  /** Apply the "default" empty params (clears all filters). */
  applyDefault(): void;
  /** Export user views as a JSON string. */
  exportJSON(): string;
  /** Import views from a JSON string (deduped by name, case-insensitive). */
  importJSON(json: string): { imported: number; skipped: number; error?: string };
  /** Re-read from localStorage (for tests / cross-tab sync). */
  refresh(): void;
}

export function createSavedViewsStore(scope: string, pathname: string): SavedViewsStore {
  const factories = factoryViewsFor(scope);
  // Rune-backed state — Svelte 5 tracks mutations on plain arrays inside $state.
  let userViews = $state<SavedView[]>(loadUserViews(scope));

  const currentParams = $derived(paramsFromUrl(page.url.searchParams));

  const combined = $derived<SavedView[]>([...factories, ...userViews]);

  const active = $derived(combined.find((v) => paramsEqual(v.params, currentParams)) ?? null);
  const modified = $derived(active === null && Object.keys(currentParams).length > 0);

  function persist(): void {
    persistUserViews(scope, userViews);
  }

  function nameTaken(name: string, ignoreId?: string): boolean {
    const lower = name.trim().toLowerCase();
    return combined.some((v) => v.id !== ignoreId && v.name.trim().toLowerCase() === lower);
  }

  function saveCurrent(name: string, opts?: { pinned?: boolean }): SaveResult {
    const trimmed = name.trim();
    if (!trimmed) return { ok: false, error: 'name-required' };
    if (nameTaken(trimmed)) return { ok: false, error: 'name-taken' };
    const view: SavedView = {
      id: generateId(),
      name: trimmed,
      scope,
      params: { ...currentParams },
      createdAt: new SvelteDate().toISOString(),
      pinned: opts?.pinned ?? false,
    };
    userViews = [...userViews, view];
    persist();
    return { ok: true, view };
  }

  function updateView(id: string, patch: Partial<Pick<SavedView, 'name' | 'pinned'>>): SaveResult {
    const idx = userViews.findIndex((v) => v.id === id);
    if (idx < 0) return { ok: false, error: 'name-required' };
    const current = userViews[idx]!;
    const nextName = (patch.name ?? current.name).trim();
    if (!nextName) return { ok: false, error: 'name-required' };
    if (nameTaken(nextName, id)) return { ok: false, error: 'name-taken' };
    const updated: SavedView = {
      ...current,
      name: nextName,
      ...(patch.pinned !== undefined ? { pinned: patch.pinned } : {}),
    };
    userViews = [...userViews.slice(0, idx), updated, ...userViews.slice(idx + 1)];
    persist();
    return { ok: true, view: updated };
  }

  function deleteView(id: string): boolean {
    // Factory views are immutable.
    if (factories.some((f) => f.id === id)) return false;
    const before = userViews.length;
    userViews = userViews.filter((v) => v.id !== id);
    if (userViews.length === before) return false;
    persist();
    return true;
  }

  function applyParams(params: ViewParams): void {
    const qs = paramsToSearch(params);
    const target = `${pathname}${qs ? `?${qs}` : ''}`;
    // eslint-disable-next-line svelte/no-navigation-without-resolve
    void goto(target, { keepFocus: true, noScroll: true, replaceState: true });
  }

  function applyView(view: SavedView): void {
    applyParams(view.params);
  }

  function applyDefault(): void {
    applyParams({});
  }

  function exportJSON(): string {
    // Pretty-print so users can hand-edit / diff exports.
    return JSON.stringify(
      {
        version: 1,
        scope,
        exportedAt: new SvelteDate().toISOString(),
        views: userViews,
      },
      null,
      2,
    );
  }

  function importJSON(json: string): { imported: number; skipped: number; error?: string } {
    let parsed: unknown;
    try {
      parsed = JSON.parse(json);
    } catch (e) {
      return { imported: 0, skipped: 0, error: `invalid JSON: ${(e as Error).message}` };
    }
    const incoming: unknown =
      parsed && typeof parsed === 'object' && 'views' in parsed
        ? (parsed as { views: unknown }).views
        : parsed;
    if (!Array.isArray(incoming)) {
      return { imported: 0, skipped: 0, error: 'expected an array of views' };
    }
    let imported = 0;
    let skipped = 0;
    const next: SavedView[] = [...userViews];
    for (const raw of incoming) {
      if (!raw || typeof raw !== 'object') {
        skipped++;
        continue;
      }
      const v = raw as Partial<SavedView>;
      if (typeof v.name !== 'string' || typeof v.params !== 'object' || v.params === null) {
        skipped++;
        continue;
      }
      const lower = v.name.trim().toLowerCase();
      const dupe =
        next.some((x) => x.name.trim().toLowerCase() === lower) ||
        factories.some((x) => x.name.trim().toLowerCase() === lower);
      if (dupe || !v.name.trim()) {
        skipped++;
        continue;
      }
      next.push({
        id: generateId(),
        name: v.name.trim(),
        scope,
        params: v.params as ViewParams,
        createdAt: typeof v.createdAt === 'string' ? v.createdAt : new SvelteDate().toISOString(),
        pinned: v.pinned === true,
      });
      imported++;
    }
    userViews = next;
    persist();
    return { imported, skipped };
  }

  function refresh(): void {
    userViews = loadUserViews(scope);
  }

  return {
    get views() {
      return combined;
    },
    get userViews() {
      return userViews;
    },
    get factoryViews() {
      return factories;
    },
    get active() {
      return active;
    },
    get modified() {
      return modified;
    },
    saveCurrent,
    updateView,
    deleteView,
    applyView,
    applyDefault,
    exportJSON,
    importJSON,
    refresh,
  };
}
