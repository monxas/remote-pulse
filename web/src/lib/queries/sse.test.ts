/**
 * Unit tests for the SSE bridge.
 *
 * We can't exercise the full `useLiveStream` rune-based hook outside a
 * Svelte component scope (it calls `$state` + `onDestroy`), but the
 * piece that needs the most coverage is the pure exponential-backoff
 * helper. The component-level behaviour is covered by the
 * `realtime.spec.ts` Playwright flow.
 */

import { describe, it, expect } from 'vitest';
import { nextBackoff } from './sse.svelte';

describe('nextBackoff', () => {
  it('doubles the current delay', () => {
    expect(nextBackoff(1_000)).toBe(2_000);
    expect(nextBackoff(2_000)).toBe(4_000);
    expect(nextBackoff(4_000)).toBe(8_000);
    expect(nextBackoff(8_000)).toBe(16_000);
  });

  it('caps the delay at 30s', () => {
    expect(nextBackoff(16_000)).toBe(30_000);
    expect(nextBackoff(30_000)).toBe(30_000);
    expect(nextBackoff(60_000)).toBe(30_000);
  });

  it('produces the documented 1s→2s→4s→8s→16s→30s sequence', () => {
    const sequence: number[] = [];
    let cur = 1_000;
    for (let i = 0; i < 6; i += 1) {
      sequence.push(cur);
      cur = nextBackoff(cur);
    }
    expect(sequence).toEqual([1_000, 2_000, 4_000, 8_000, 16_000, 30_000]);
  });
});
