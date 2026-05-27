import { describe, it, expect, beforeEach } from 'vitest';
import {
  FACTORY_VIEWS,
  factoryViewsFor,
  loadUserViews,
  paramsEqual,
  paramsFromUrl,
  paramsToSearch,
  persistUserViews,
  slugify,
  storageKey,
  type SavedView,
} from './saved-views.svelte';

// The Svelte 5 rune-backed `createSavedViewsStore` reads `$app/state.page`
// and calls `goto`, which require a Svelte tracking root + SvelteKit
// runtime. We exercise it end-to-end via Playwright; here we cover the
// pure helpers (which carry the bulk of the logic) and the
// localStorage I/O contract that wraps them.

beforeEach(() => {
  try {
    window.localStorage.clear();
  } catch {
    /* ignore in non-browser test envs */
  }
});

describe('paramsFromUrl + paramsEqual', () => {
  it('reads scalar + repeated params', () => {
    const sp = new URLSearchParams('a=1&b=x&b=y&c=z');
    expect(paramsFromUrl(sp)).toEqual({ a: '1', b: ['x', 'y'], c: 'z' });
  });

  it('round-trips through paramsToSearch (sorted keys)', () => {
    const original = { b: 'x', a: '1', c: ['z', 'y'] };
    const qs = paramsToSearch(original);
    const restored = paramsFromUrl(new URLSearchParams(qs));
    expect(paramsEqual(restored, original)).toBe(true);
  });

  it('compares params ignoring array ordering', () => {
    expect(paramsEqual({ a: ['1', '2'] }, { a: ['2', '1'] })).toBe(true);
    expect(paramsEqual({ a: ['1'] }, { a: '1' })).toBe(true);
    expect(paramsEqual({ a: '1' }, { a: '2' })).toBe(false);
    expect(paramsEqual({ a: '1' }, { a: '1', b: '2' })).toBe(false);
  });

  it('treats an empty url as an empty params object', () => {
    expect(paramsFromUrl(new URLSearchParams(''))).toEqual({});
  });
});

describe('slugify', () => {
  it('lowercases + collapses non-alnum', () => {
    expect(slugify('Hello World!')).toBe('hello-world');
    expect(slugify('  weird___name  ')).toBe('weird-name');
  });

  it('strips diacritics so unicode names give stable ids', () => {
    expect(slugify('Producción')).toBe('produccion');
  });
});

describe('factoryViewsFor', () => {
  it('returns a defensive copy', () => {
    const a = factoryViewsFor('fleet');
    const b = factoryViewsFor('fleet');
    expect(a).not.toBe(b);
    expect(a.length).toBeGreaterThan(0);
    // Mutating the returned copy must not affect the canonical source.
    a[0]!.name = 'mutated';
    const c = factoryViewsFor('fleet');
    expect(c[0]!.name).not.toBe('mutated');
  });

  it('exposes the documented factory scopes', () => {
    expect(Object.keys(FACTORY_VIEWS).sort()).toEqual(['audit', 'commands', 'fleet']);
    // Each factory view is marked `factory: true` so the UI can hide
    // destructive actions safely.
    for (const scope of Object.keys(FACTORY_VIEWS)) {
      for (const v of FACTORY_VIEWS[scope]!) {
        expect(v.factory).toBe(true);
        expect(v.scope).toBe(scope);
      }
    }
  });

  it('audit "Today" maps to range=24h', () => {
    const today = FACTORY_VIEWS.audit!.find((v) => v.name === 'Today');
    expect(today).toBeDefined();
    expect(today!.params).toEqual({ range: '24h' });
  });

  it('fleet "All hosts" has empty params (matches a clean URL)', () => {
    const all = FACTORY_VIEWS.fleet!.find((v) => v.name === 'All hosts');
    expect(all).toBeDefined();
    expect(Object.keys(all!.params).length).toBe(0);
  });
});

describe('localStorage round-trip', () => {
  it('persist + load returns the same shape', () => {
    const v: SavedView = {
      id: 'u_1',
      name: 'My audit',
      scope: 'audit',
      params: { action_prefix: 'host.', range: '24h' },
      createdAt: '2026-01-01T00:00:00.000Z',
      pinned: true,
    };
    persistUserViews('audit', [v]);
    const loaded = loadUserViews('audit');
    expect(loaded).toEqual([v]);
  });

  it('does NOT persist factory views (they live in code)', () => {
    persistUserViews('audit', [
      ...factoryViewsFor('audit'),
      {
        id: 'u_keep',
        name: 'Mine',
        scope: 'audit',
        params: {},
        createdAt: '2026-01-01T00:00:00.000Z',
      },
    ]);
    const loaded = loadUserViews('audit');
    expect(loaded).toHaveLength(1);
    expect(loaded[0]!.id).toBe('u_keep');
  });

  it('silently returns [] when the storage value is corrupt', () => {
    window.localStorage.setItem(storageKey('audit'), '{not json');
    expect(loadUserViews('audit')).toEqual([]);
  });

  it('silently returns [] when storage holds a non-array', () => {
    window.localStorage.setItem(storageKey('audit'), '{"a": 1}');
    expect(loadUserViews('audit')).toEqual([]);
  });

  it('scopes are isolated', () => {
    persistUserViews('audit', [
      {
        id: 'u_a',
        name: 'Audit one',
        scope: 'audit',
        params: {},
        createdAt: '2026-01-01T00:00:00.000Z',
      },
    ]);
    persistUserViews('fleet', [
      {
        id: 'u_f',
        name: 'Fleet one',
        scope: 'fleet',
        params: {},
        createdAt: '2026-01-01T00:00:00.000Z',
      },
    ]);
    expect(loadUserViews('audit').map((v) => v.id)).toEqual(['u_a']);
    expect(loadUserViews('fleet').map((v) => v.id)).toEqual(['u_f']);
  });
});

describe('storageKey', () => {
  it('namespaces by scope under the rp prefix', () => {
    expect(storageKey('audit')).toBe('rp:saved-views:audit');
    expect(storageKey('fleet')).toBe('rp:saved-views:fleet');
  });
});
