/**
 * Generic sortable + filterable table state, persisted to URL search params.
 *
 * Each table on a page gets its own instance and namespaces its params with a
 * prefix so two tables on the same route (e.g. Settings Groups + Users) don't
 * clobber each other. Default param names:
 *   - `<prefix>sort` — column key (matches one of `searchable` or a custom one)
 *   - `<prefix>dir`  — 'asc' | 'desc'
 *   - `<prefix>q`    — substring search (case-insensitive, matches all fields in `searchable`)
 *
 * URL is the source of truth so refreshes + shareable links Just Work.
 */

import { page } from '$app/state';
import { goto } from '$app/navigation';
import { SvelteURLSearchParams } from 'svelte/reactivity';

export type SortDir = 'asc' | 'desc';

type GetSortValue<T> = (row: T, key: string) => unknown;

export interface TableStateOptions<T> {
  /** URL-param prefix so multiple tables can coexist on the same page (e.g. 'g_'). */
  prefix?: string;
  /** Fields used by the search box for substring matching. */
  searchable: ReadonlyArray<keyof T & string>;
  /** Per-key extractor for sort values (defaults to row[key]). */
  getSortValue?: GetSortValue<T>;
}

export interface TableState<T> {
  readonly sortKey: string | null;
  readonly sortDir: SortDir | null;
  readonly query: string;
  /** The filtered + sorted rows. */
  readonly view: T[];
  /** Cycle a column header through asc → desc → off. */
  toggleSort(key: string): void;
  /** Set the search query (URL-persisted). */
  setQuery(q: string): void;
  /** Clear sort + query. */
  reset(): void;
  /** Aria-sort attribute value for a column header. */
  ariaSort(key: string): 'ascending' | 'descending' | 'none';
}

function defaultGetSortValue<T>(row: T, key: string): unknown {
  return (row as unknown as Record<string, unknown>)[key];
}

export function compareValues(a: unknown, b: unknown): number {
  // Nullish always sorts to the end so empty cells don't lead the table.
  const an = a === null || a === undefined || a === '';
  const bn = b === null || b === undefined || b === '';
  if (an && bn) return 0;
  if (an) return 1;
  if (bn) return -1;
  if (typeof a === 'number' && typeof b === 'number') return a - b;
  if (typeof a === 'boolean' && typeof b === 'boolean') return a === b ? 0 : a ? 1 : -1;
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: 'base' });
}

/**
 * Pure projection used by both `createTableState` and unit tests. Applies
 * the query filter + sort to a snapshot of rows and returns a new array.
 */
export function applyTableState<T>(
  rows: ReadonlyArray<T>,
  query: string,
  sortKey: string | null,
  sortDir: SortDir | null,
  searchable: ReadonlyArray<keyof T & string>,
  getSortValue: GetSortValue<T> = defaultGetSortValue,
): T[] {
  let result = [...rows];
  if (query) {
    const needle = query.toLowerCase();
    result = result.filter((r) =>
      searchable.some((f) => {
        const v = (r as unknown as Record<string, unknown>)[f as string];
        return v !== null && v !== undefined && String(v).toLowerCase().includes(needle);
      }),
    );
  }
  if (sortKey && sortDir) {
    result.sort((a, b) => {
      const av = getSortValue(a, sortKey);
      const bv = getSortValue(b, sortKey);
      // Nullish values always sort to the end regardless of direction —
      // empty cells leading the table is confusing for operators.
      const an = av === null || av === undefined || av === '';
      const bn = bv === null || bv === undefined || bv === '';
      if (an && bn) return 0;
      if (an) return 1;
      if (bn) return -1;
      const cmp = compareValues(av, bv);
      return sortDir === 'asc' ? cmp : -cmp;
    });
  }
  return result;
}

/**
 * Pure helper for the sort cycle (unsorted → asc → desc → unsorted).
 * Returns the next (key, dir) pair given the current state and a clicked key.
 */
export function nextSortState(
  currentKey: string | null,
  currentDir: SortDir | null,
  clickedKey: string,
): { sortKey: string | null; sortDir: SortDir | null } {
  if (currentKey !== clickedKey) {
    return { sortKey: clickedKey, sortDir: 'asc' };
  }
  if (currentDir === 'asc') {
    return { sortKey: clickedKey, sortDir: 'desc' };
  }
  return { sortKey: null, sortDir: null };
}

/**
 * Factory: returns a reactive TableState bound to `rows`. Call inside a
 * component <script> — uses `$derived` so the view recomputes when either
 * the URL or the source rows change.
 *
 * The reason we expose `view` as a getter (returning the latest computed
 * array each time) is so callers can destructure once and let Svelte
 * pick up reactivity through the proxy properties.
 */
export function createTableState<T>(
  rows: () => ReadonlyArray<T>,
  opts: TableStateOptions<T>,
): TableState<T> {
  const prefix = opts.prefix ?? '';
  const SORT_KEY = `${prefix}sort`;
  const DIR_KEY = `${prefix}dir`;
  const QUERY_KEY = `${prefix}q`;

  const getSortValue = opts.getSortValue ?? defaultGetSortValue;

  // `$app/state.page` is itself a fine-grained reactive proxy in Svelte 5 /
  // SvelteKit 2, so reading inside `$derived` picks up search-param changes
  // automatically. Must be called from a component setup that has a tracking
  // root (which is the only place `$derived` is allowed anyway).
  const sortKey = $derived(page.url.searchParams.get(SORT_KEY));
  const sortDir = $derived(
    (page.url.searchParams.get(DIR_KEY) as SortDir | null) ?? null,
  );
  const query = $derived(page.url.searchParams.get(QUERY_KEY) ?? '');

  const view = $derived.by(() =>
    applyTableState(rows(), query, sortKey, sortDir, opts.searchable, getSortValue),
  );

  function updateUrl(patch: Record<string, string | null>): void {
    const current = page.url;
    const next = new SvelteURLSearchParams(current.searchParams);
    for (const [k, v] of Object.entries(patch)) {
      if (v === null || v === '') next.delete(k);
      else next.set(k, v);
    }
    const qs = next.toString();
    const target = `${current.pathname}${qs ? `?${qs}` : ''}`;
    // eslint-disable-next-line svelte/no-navigation-without-resolve
    void goto(target, { keepFocus: true, noScroll: true, replaceState: true });
  }

  function toggleSort(key: string): void {
    const next = nextSortState(sortKey, sortDir, key);
    updateUrl({ [SORT_KEY]: next.sortKey, [DIR_KEY]: next.sortDir });
  }

  function setQuery(q: string): void {
    updateUrl({ [QUERY_KEY]: q.trim() || null });
  }

  function reset(): void {
    updateUrl({ [SORT_KEY]: null, [DIR_KEY]: null, [QUERY_KEY]: null });
  }

  function ariaSort(key: string): 'ascending' | 'descending' | 'none' {
    if (sortKey !== key || !sortDir) return 'none';
    return sortDir === 'asc' ? 'ascending' : 'descending';
  }

  return {
    get sortKey() {
      return sortKey;
    },
    get sortDir() {
      return sortDir;
    },
    get query() {
      return query;
    },
    get view() {
      return view;
    },
    toggleSort,
    setQuery,
    reset,
    ariaSort,
  };
}
