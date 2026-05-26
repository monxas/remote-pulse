import { describe, it, expect } from 'vitest';
import {
  ptrStateFor,
  damp,
  PTR_THRESHOLD_PX,
  PTR_TRIGGER_PX,
  PTR_ACTIVATE_PX,
  PTR_MAX_PX,
} from './pull-to-refresh-state';

/**
 * Pull-to-refresh state machine. We deliberately keep the predicate
 * pure (no DOM) so we can prove the four transitions in isolation:
 * idle → pulling → ready → refreshing → idle.
 *
 * The DOM-bound gesture logic itself lives inside the component and
 * is exercised by the mobile Playwright spec.
 */
describe('ptrStateFor', () => {
  it('returns idle when no pull and not refreshing', () => {
    expect(ptrStateFor(0, false)).toBe('idle');
    expect(ptrStateFor(-5, false)).toBe('idle');
  });

  it('returns pulling between 1px and the trigger threshold', () => {
    expect(ptrStateFor(1, false)).toBe('pulling');
    expect(ptrStateFor(PTR_THRESHOLD_PX, false)).toBe('pulling');
    expect(ptrStateFor(PTR_TRIGGER_PX - 1, false)).toBe('pulling');
  });

  it('flips to ready once the trigger threshold is reached', () => {
    expect(ptrStateFor(PTR_TRIGGER_PX, false)).toBe('ready');
    expect(ptrStateFor(PTR_TRIGGER_PX + 50, false)).toBe('ready');
    expect(ptrStateFor(PTR_MAX_PX, false)).toBe('ready');
  });

  it('refreshing flag wins over any distance', () => {
    expect(ptrStateFor(0, true)).toBe('refreshing');
    expect(ptrStateFor(50, true)).toBe('refreshing');
    expect(ptrStateFor(PTR_TRIGGER_PX, true)).toBe('refreshing');
  });

  it('exports sane threshold ordering', () => {
    expect(PTR_ACTIVATE_PX).toBeLessThan(PTR_THRESHOLD_PX);
    expect(PTR_THRESHOLD_PX).toBeLessThan(PTR_TRIGGER_PX);
    expect(PTR_TRIGGER_PX).toBeLessThanOrEqual(PTR_MAX_PX);
  });
});

describe('damp', () => {
  it('is identity below the trigger threshold', () => {
    expect(damp(0)).toBe(0);
    expect(damp(50)).toBe(50);
    expect(damp(PTR_TRIGGER_PX)).toBe(PTR_TRIGGER_PX);
  });

  it('applies sqrt-style falloff past the trigger', () => {
    // 6px overshoot → +6 (sqrt of 6*6=36 == 6)
    expect(damp(PTR_TRIGGER_PX + 6)).toBeCloseTo(PTR_TRIGGER_PX + 6, 5);
    // 24px overshoot → +12 (sqrt of 24*6=144 == 12)
    expect(damp(PTR_TRIGGER_PX + 24)).toBeCloseTo(PTR_TRIGGER_PX + 12, 5);
  });

  it('is monotonically increasing', () => {
    let prev = damp(0);
    for (let d = 1; d <= 400; d += 5) {
      const cur = damp(d);
      expect(cur).toBeGreaterThanOrEqual(prev);
      prev = cur;
    }
  });
});
