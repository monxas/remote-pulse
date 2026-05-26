import { describe, it, expect } from 'vitest';
import { computeSelectAllState } from './host-selection.svelte';

// We test the pure helper rather than the rune-backed `createHostSelection`
// to keep the suite environment-free. The interactive behaviour (toggle
// in / toggle out + indeterminate header) is covered end-to-end by the
// Playwright bulk-command spec.

describe('computeSelectAllState', () => {
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
    // The selection may include rows that are currently filtered out of
    // view; we only care whether the visible IDs are all selected.
    expect(computeSelectAllState(['a'], new Set(['a', 'b', 'c']))).toBe('all');
  });

  it('returns "some" for a strict subset', () => {
    expect(computeSelectAllState(['a', 'b', 'c'], new Set(['b']))).toBe('some');
  });
});
