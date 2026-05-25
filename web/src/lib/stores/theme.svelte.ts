/**
 * Theme preference store — `light` / `dark` / `system`.
 *
 * Persisted to `localStorage['rp-theme']`. The pre-paint script in
 * `app.html` reads the same key to set the initial class so we never get
 * a flash of the wrong theme. Mutating this store re-applies the class.
 */

import { browser } from '$app/environment';

export type ThemePref = 'light' | 'dark' | 'system';
export type ResolvedTheme = 'light' | 'dark';

const STORAGE_KEY = 'rp-theme';

function readStored(): ThemePref {
  if (!browser) return 'system';
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v === 'light' || v === 'dark' || v === 'system') return v;
  } catch {
    /* SSR / sandboxed iframe */
  }
  return 'system';
}

function resolveTheme(pref: ThemePref): ResolvedTheme {
  if (pref === 'light' || pref === 'dark') return pref;
  if (!browser) return 'dark';
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

function applyTheme(resolved: ResolvedTheme) {
  if (!browser) return;
  const html = document.documentElement;
  html.dataset.theme = resolved;
  html.classList.remove('light-theme', 'dark-theme');
  html.classList.add(`${resolved}-theme`);
}

function createThemeStore() {
  let pref = $state<ThemePref>(readStored());
  let resolved = $state<ResolvedTheme>(resolveTheme(pref));

  function set(next: ThemePref) {
    pref = next;
    if (browser) {
      try {
        localStorage.setItem(STORAGE_KEY, next);
      } catch {
        /* ignore */
      }
    }
    resolved = resolveTheme(next);
    applyTheme(resolved);
  }

  function cycle() {
    const order: ThemePref[] = ['dark', 'light', 'system'];
    const i = order.indexOf(pref);
    set(order[(i + 1) % order.length] ?? 'dark');
  }

  return {
    get pref() {
      return pref;
    },
    get resolved() {
      return resolved;
    },
    set,
    cycle,
  };
}

export const themeStore = createThemeStore();
