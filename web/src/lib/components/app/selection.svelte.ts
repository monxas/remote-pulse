/**
 * Generic multi-select state container.
 *
 * Promoted from the original `host-selection.svelte.ts` so the Settings
 * page (Users + Groups tabs) and any future table can reuse the same
 * Svelte 5 rune-backed selection primitive. The store is intentionally
 * provider-agnostic — it stores opaque string IDs and exposes the
 * standard select/toggle/clear primitives plus a derived
 * `selectAllState` used to render an indeterminate header checkbox.
 *
 * `host-selection.svelte.ts` is kept as a thin compatibility wrapper
 * that re-exports `createHostSelection = createSelection` so existing
 * callers (and tests) keep working without churn.
 */

import { SvelteSet } from 'svelte/reactivity';

export type SelectAllState = 'none' | 'some' | 'all';

/**
 * Compute the tri-state for an "all visible" header checkbox.
 *
 * - `none` -> none of the visible IDs are currently selected
 * - `some` -> a strict subset is selected (renders indeterminate)
 * - `all`  -> every visible ID is selected
 *
 * Visible IDs that aren't present in `selected` are ignored, which means
 * the header reflects only the currently-rendered rows. That matches the
 * UX of most data tables (Linear, GitHub, Notion): "select all" toggles
 * what you can see, not the whole world.
 */
export function computeSelectAllState<T extends string = string>(
  visibleIds: ReadonlyArray<T>,
  selected: ReadonlySet<T>,
): SelectAllState {
  if (visibleIds.length === 0) return 'none';
  let hits = 0;
  for (const id of visibleIds) {
    if (selected.has(id)) hits += 1;
  }
  if (hits === 0) return 'none';
  if (hits === visibleIds.length) return 'all';
  return 'some';
}

export interface ISelection<T extends string = string> {
  readonly ids: ReadonlyArray<T>;
  readonly count: number;
  has(id: T): boolean;
  toggle(id: T): void;
  add(id: T): void;
  remove(id: T): void;
  clear(): void;
  setMany(ids: ReadonlyArray<T>): void;
  /** Toggle every visible ID: if all are selected, deselect them; else select all visible. */
  toggleAllVisible(visibleIds: ReadonlyArray<T>): void;
  selectAllState(visibleIds: ReadonlyArray<T>): SelectAllState;
}

export function createSelection<T extends string = string>(): ISelection<T> {
  // Reactive Set so $state proxies mutations through Svelte's runtime;
  // a plain Set wouldn't trigger reactive updates when callers mutate
  // it in place. See svelte/prefer-svelte-reactivity eslint rule.
  const store = new SvelteSet<T>();

  function snapshot(): ReadonlyArray<T> {
    return [...store].sort();
  }

  return {
    get ids() {
      return snapshot();
    },
    get count() {
      return store.size;
    },
    has(id) {
      return store.has(id);
    },
    toggle(id) {
      if (store.has(id)) store.delete(id);
      else store.add(id);
    },
    add(id) {
      store.add(id);
    },
    remove(id) {
      store.delete(id);
    },
    clear() {
      store.clear();
    },
    setMany(ids) {
      store.clear();
      for (const id of ids) store.add(id);
    },
    toggleAllVisible(visibleIds) {
      const state = computeSelectAllState(visibleIds, store);
      if (state === 'all') {
        for (const id of visibleIds) store.delete(id);
      } else {
        for (const id of visibleIds) store.add(id);
      }
    },
    selectAllState(visibleIds) {
      return computeSelectAllState(visibleIds, store);
    },
  };
}
