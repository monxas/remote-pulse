import { describe, it, expect } from 'vitest';
import { computeSelectAllState } from './selection.svelte';

// We test the pure helper here. The interactive `createSelection`
// behaviour is exercised end-to-end by the Playwright bulk-command and
// settings-bulk specs.

describe('computeSelectAllState (generic)', () => {
  it('returns "none" when no visible row is selected', () => {
    expect(computeSelectAllState(['a', 'b', 'c'], new Set())).toBe('none');
  });

  it('returns "none" when the visible set is empty', () => {
    expect(computeSelectAllState([], new Set(['a']))).toBe('none');
  });

  it('returns "all" when every visible row is selected', () => {
    expect(computeSelectAllState(['a', 'b'], new Set(['a', 'b']))).toBe('all');
  });

  it('returns "all" even when selection extends past the visible set', () => {
    expect(computeSelectAllState(['a'], new Set(['a', 'b', 'c']))).toBe('all');
  });

  it('returns "some" for a strict subset', () => {
    expect(computeSelectAllState(['a', 'b', 'c'], new Set(['b']))).toBe('some');
  });

  it('works with branded string-literal types (compile-time check)', () => {
    // Generic-typed: the consumer can use a more specific T such as
    // `UserId` / `GroupName` and the helper still accepts it.
    type UserId = `u_${string}`;
    const visible: ReadonlyArray<UserId> = ['u_1', 'u_2'];
    const sel: ReadonlySet<UserId> = new Set(['u_1' as UserId]);
    expect(computeSelectAllState(visible, sel)).toBe('some');
  });
});
