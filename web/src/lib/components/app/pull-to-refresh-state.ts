/**
 * Pure-function state helpers for `PullToRefresh.svelte`. Extracted to
 * a plain `.ts` module so they can be unit-tested without a Svelte
 * compile pass (and so we don't pollute the component's `<script
 * context="module">` with TS-vs-runes conflicts).
 *
 * The component imports + re-uses these constants verbatim — DO NOT
 * duplicate the values inline in the .svelte file.
 */

/**
 * Tunables. THRESHOLD = pull distance at which the indicator label
 * flips to "release to refresh"; TRIGGER = max pull distance at which
 * we commit to a refresh on release (acts as progress ceiling);
 * ACTIVATE = how much we must move before we start visually tracking
 * the gesture (filters out micro-jitter).
 *
 * Values chosen to mirror Twitter / native iOS patterns: 80px is
 * "intent to refresh", 120px is "you are definitely doing this".
 */
export const PTR_ACTIVATE_PX = 8;
export const PTR_THRESHOLD_PX = 80;
export const PTR_TRIGGER_PX = 120;
export const PTR_MAX_PX = 160;

export type PtrState = 'idle' | 'pulling' | 'ready' | 'refreshing';

/**
 * Map a pull distance + refreshing flag to the visual indicator state.
 * Pure and DOM-free so the state machine is unit-testable in jsdom.
 */
export function ptrStateFor(distance: number, refreshing: boolean): PtrState {
  if (refreshing) return 'refreshing';
  if (distance <= 0) return 'idle';
  if (distance >= PTR_TRIGGER_PX) return 'ready';
  return 'pulling';
}

/**
 * Square-root falloff past the trigger threshold so the rubber-band
 * feels increasingly resistive but never lets the indicator fly off.
 * Below the threshold the pull is 1:1 with the finger.
 */
export function damp(d: number): number {
  if (d <= PTR_TRIGGER_PX) return d;
  const over = d - PTR_TRIGGER_PX;
  return PTR_TRIGGER_PX + Math.sqrt(over * 6);
}
