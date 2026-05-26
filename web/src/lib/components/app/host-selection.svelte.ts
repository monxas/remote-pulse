/**
 * Multi-select state container for the Fleet table.
 *
 * Selection lives in a Svelte 5 rune-backed class instance so the Fleet
 * page can pass the same selection both to the `HostTable` (to render
 * checkboxes + indeterminate state) and to the `BulkActionBar` (to show
 * the count + open the bulk dialog). The state is scoped per-page; the
 * Fleet page creates one with `createHostSelection()` and clears it on
 * unmount-ish moments (e.g. after a successful bulk issue).
 *
 * The store is intentionally provider-agnostic — it stores opaque host
 * IDs and exposes the standard select/toggle/clear primitives plus a
 * derived `selectAllState` used to render an indeterminate header
 * checkbox.
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
export function computeSelectAllState(
  visibleIds: ReadonlyArray<string>,
  selected: ReadonlySet<string>,
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

export interface IHostSelection {
  readonly ids: ReadonlyArray<string>;
  readonly count: number;
  has(id: string): boolean;
  toggle(id: string): void;
  add(id: string): void;
  remove(id: string): void;
  clear(): void;
  setMany(ids: ReadonlyArray<string>): void;
  /** Toggle every visible ID: if all are selected, deselect them; else select all visible. */
  toggleAllVisible(visibleIds: ReadonlyArray<string>): void;
  selectAllState(visibleIds: ReadonlyArray<string>): SelectAllState;
}

export function createHostSelection(): IHostSelection {
  // Reactive Set so $state proxies mutations through Svelte's runtime;
  // a plain Set wouldn't trigger reactive updates when callers mutate
  // it in place. See svelte/prefer-svelte-reactivity eslint rule.
  const store = new SvelteSet<string>();

  function snapshot(): ReadonlyArray<string> {
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
