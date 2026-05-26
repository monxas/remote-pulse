import { describe, it, expect } from 'vitest';
import {
  applyTableState,
  compareValues,
  nextSortState,
} from './table-state.svelte';

type Row = { name: string; count: number; desc: string | null };

const ROWS: Row[] = [
  { name: 'beta', count: 3, desc: 'second' },
  { name: 'alpha', count: 1, desc: 'first' },
  { name: 'gamma', count: 10, desc: null },
];

describe('compareValues', () => {
  it('sorts numbers numerically', () => {
    expect(compareValues(2, 10)).toBeLessThan(0);
    expect(compareValues(10, 2)).toBeGreaterThan(0);
  });

  it('sorts strings with natural numeric collation', () => {
    expect(compareValues('item-2', 'item-10')).toBeLessThan(0);
  });

  it('places nullish values at the end', () => {
    expect(compareValues(null, 'a')).toBeGreaterThan(0);
    expect(compareValues('a', null)).toBeLessThan(0);
    expect(compareValues(undefined, undefined)).toBe(0);
    expect(compareValues('', 'a')).toBeGreaterThan(0);
  });
});

describe('nextSortState', () => {
  it('switches to a new key with asc when key changes', () => {
    expect(nextSortState(null, null, 'name')).toEqual({ sortKey: 'name', sortDir: 'asc' });
    expect(nextSortState('count', 'asc', 'name')).toEqual({ sortKey: 'name', sortDir: 'asc' });
  });

  it('cycles asc -> desc on same key', () => {
    expect(nextSortState('name', 'asc', 'name')).toEqual({ sortKey: 'name', sortDir: 'desc' });
  });

  it('cycles desc -> unsorted on same key', () => {
    expect(nextSortState('name', 'desc', 'name')).toEqual({ sortKey: null, sortDir: null });
  });
});

describe('applyTableState', () => {
  it('returns input order when unsorted + no query', () => {
    const out = applyTableState(ROWS, '', null, null, ['name', 'desc']);
    expect(out.map((r) => r.name)).toEqual(['beta', 'alpha', 'gamma']);
  });

  it('filters by query against listed searchable fields (case-insensitive)', () => {
    const out = applyTableState(ROWS, 'FIRST', null, null, ['name', 'desc']);
    expect(out.map((r) => r.name)).toEqual(['alpha']);
  });

  it('ignores non-searchable fields when filtering', () => {
    // count is not in the searchable list, so '10' must not match
    const out = applyTableState(ROWS, '10', null, null, ['name', 'desc']);
    expect(out).toEqual([]);
  });

  it('sorts ascending by string field', () => {
    const out = applyTableState(ROWS, '', 'name', 'asc', ['name', 'desc']);
    expect(out.map((r) => r.name)).toEqual(['alpha', 'beta', 'gamma']);
  });

  it('sorts descending by string field', () => {
    const out = applyTableState(ROWS, '', 'name', 'desc', ['name', 'desc']);
    expect(out.map((r) => r.name)).toEqual(['gamma', 'beta', 'alpha']);
  });

  it('sorts numeric fields using getSortValue', () => {
    const out = applyTableState(
      ROWS,
      '',
      'count',
      'asc',
      ['name'],
      (row, key) => (row as unknown as Record<string, unknown>)[key],
    );
    expect(out.map((r) => r.count)).toEqual([1, 3, 10]);
  });

  it('places null sort values at the end regardless of direction', () => {
    const asc = applyTableState(ROWS, '', 'desc', 'asc', ['name']);
    expect(asc.map((r) => r.name)).toEqual(['alpha', 'beta', 'gamma']);
    const desc = applyTableState(ROWS, '', 'desc', 'desc', ['name']);
    // 'gamma' has desc=null → still at the end
    expect(desc[desc.length - 1]?.name).toBe('gamma');
  });

  it('does not mutate the input array', () => {
    const before = [...ROWS];
    applyTableState(ROWS, '', 'name', 'asc', ['name']);
    expect(ROWS).toEqual(before);
  });

  it('combines query + sort', () => {
    const out = applyTableState(
      [
        { name: 'beta', count: 3, desc: 'a-search-hit' },
        { name: 'alpha', count: 1, desc: 'a-search-hit' },
        { name: 'gamma', count: 10, desc: 'miss' },
      ],
      'search',
      'name',
      'desc',
      ['desc'],
    );
    expect(out.map((r) => r.name)).toEqual(['beta', 'alpha']);
  });
});
