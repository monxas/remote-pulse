/**
 * Pure helpers for the /audit filter bar — extracted so we can unit-test
 * the URL ↔ params translation without a Svelte component harness.
 *
 * The component (``+page.svelte``) is the source of truth for which params
 * the audit endpoint accepts; these helpers stay narrow and focused on the
 * date-range presets + URL serialisation patch shape used by ``updateUrl``.
 */

import {
  ALL_AUDIT_ACTIONS,
  type AuditAction,
  type AuditQueryParams,
  type AuditTargetType,
} from '$lib/api';

export type Range = 'today' | '24h' | '7d' | '30d' | 'all' | 'custom';

export const RANGES: ReadonlyArray<{ value: Range; label: string }> = [
  { value: 'today', label: 'Today' },
  { value: '24h', label: '24h' },
  { value: '7d', label: '7d' },
  { value: '30d', label: '30d' },
  { value: 'all', label: 'All time' },
  { value: 'custom', label: 'Custom' },
];

/**
 * Compute the ``since`` ISO string for a preset range. Returns ``undefined``
 * for ``custom`` (the caller reads ``?since=`` from the URL) and ``all``
 * (no lower bound).
 *
 * ``now`` is injectable so tests can pin the clock.
 */
export function sinceFor(range: Range, now: Date = new Date()): string | undefined {
  if (range === 'custom' || range === 'all') return undefined;
  if (range === 'today') {
    const start = new Date(now);
    start.setHours(0, 0, 0, 0);
    return start.toISOString();
  }
  const ms = range === '24h' ? 86_400_000 : range === '7d' ? 604_800_000 : 2_592_000_000;
  return new Date(now.getTime() - ms).toISOString();
}

/**
 * Build an ``AuditQueryParams`` object from a ``URLSearchParams``-like
 * object. ``action_prefix`` takes precedence over the explicit ``action``
 * list (the backend rejects both with 422), but the action list survives in
 * the URL so toggling the prefix off restores the user's pill selection.
 */
export function paramsFromSearch(
  sp: { get(name: string): string | null; getAll(name: string): string[] },
  now: Date = new Date(),
): AuditQueryParams {
  const actor = sp.get('actor') ?? undefined;
  const actionList = sp
    .getAll('action')
    .filter((a): a is AuditAction => (ALL_AUDIT_ACTIONS as ReadonlyArray<string>).includes(a));
  const actionPrefix = sp.get('action_prefix') ?? undefined;
  const targetType = (sp.get('target_type') as AuditTargetType | null) ?? undefined;
  const range = (sp.get('range') ?? '7d') as Range;
  const since = range === 'custom' ? (sp.get('since') ?? undefined) : sinceFor(range, now);
  const until = range === 'custom' ? (sp.get('until') ?? undefined) : undefined;
  return {
    actor,
    action: actionPrefix ? undefined : actionList.length > 0 ? actionList : undefined,
    action_prefix: actionPrefix,
    target_type: targetType,
    since,
    until,
    limit: 100,
  };
}

/**
 * Patch object passed to ``updateUrl`` when "Clear filters" fires. Centralised
 * so the unit test can assert the contract without rendering the page.
 */
export const CLEAR_FILTERS_PATCH: Record<string, string | string[] | null> = {
  actor: null,
  action: [],
  action_prefix: null,
  target_type: null,
  range: '7d',
  since: null,
  until: null,
};
