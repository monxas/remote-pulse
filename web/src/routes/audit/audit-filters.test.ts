import { describe, it, expect } from 'vitest';
import {
  CLEAR_FILTERS_PATCH,
  RANGES,
  paramsFromSearch,
  sinceFor,
  sortActionsByFrequency,
  type Range,
} from './audit-filters';
import type { AuditAction } from '$lib/api';

describe('RANGES', () => {
  it('exposes the six preset ranges in stable order', () => {
    expect(RANGES.map((r) => r.value)).toEqual(['today', '24h', '7d', '30d', 'all', 'custom']);
  });
});

describe('sinceFor', () => {
  const NOW = new Date('2026-05-26T12:34:56.000Z');

  it('returns undefined for "all" and "custom"', () => {
    expect(sinceFor('all', NOW)).toBeUndefined();
    expect(sinceFor('custom', NOW)).toBeUndefined();
  });

  it('returns midnight-of-today for "today"', () => {
    const iso = sinceFor('today', NOW)!;
    const d = new Date(iso);
    // Midnight, same day as NOW.
    expect(d.getUTCFullYear()).toBe(NOW.getUTCFullYear());
    // We use local midnight, not UTC midnight — checking the iso ends at
    // an hour boundary is a portable smoke test.
    expect(iso).toMatch(/T\d{2}:00:00\.000Z$/);
  });

  it('returns now - 24h for "24h"', () => {
    const iso = sinceFor('24h', NOW)!;
    expect(new Date(iso).getTime()).toBe(NOW.getTime() - 86_400_000);
  });

  it('returns now - 7d for "7d"', () => {
    const iso = sinceFor('7d', NOW)!;
    expect(new Date(iso).getTime()).toBe(NOW.getTime() - 604_800_000);
  });

  it('returns now - 30d for "30d"', () => {
    const iso = sinceFor('30d', NOW)!;
    expect(new Date(iso).getTime()).toBe(NOW.getTime() - 2_592_000_000);
  });

  it('all preset Range values resolve without throwing', () => {
    for (const r of RANGES) {
      // Should never throw — paranoia smoke test in case Range adds values.
      expect(() => sinceFor(r.value as Range, NOW)).not.toThrow();
    }
  });
});

function mkSearch(qs: string): URLSearchParams {
  return new URLSearchParams(qs);
}

describe('paramsFromSearch (URL → AuditQueryParams)', () => {
  const NOW = new Date('2026-05-26T12:00:00.000Z');

  it('defaults to range=7d with no since/until on empty search', () => {
    const p = paramsFromSearch(mkSearch(''), NOW);
    expect(p.action).toBeUndefined();
    expect(p.actor).toBeUndefined();
    expect(p.target_type).toBeUndefined();
    expect(p.until).toBeUndefined();
    expect(p.since).toBe(new Date(NOW.getTime() - 604_800_000).toISOString());
    expect(p.limit).toBe(100);
  });

  it('extracts actor, multi-action, and target_type', () => {
    const p = paramsFromSearch(
      mkSearch('actor=alice@x&action=command.issued&action=command.failed&target_type=command'),
      NOW,
    );
    expect(p.actor).toBe('alice@x');
    expect(p.action).toEqual(['command.issued', 'command.failed']);
    expect(p.target_type).toBe('command');
  });

  it('ignores unknown action values silently', () => {
    const p = paramsFromSearch(mkSearch('action=command.issued&action=not.a.real.action'), NOW);
    expect(p.action).toEqual(['command.issued']);
  });

  it('drops the action list when action_prefix is set', () => {
    // Backend rejects (action + action_prefix) with 422 — UI must choose.
    const p = paramsFromSearch(mkSearch('action=command.issued&action_prefix=settings.'), NOW);
    expect(p.action).toBeUndefined();
    expect(p.action_prefix).toBe('settings.');
  });

  it('honours range=custom with literal since/until', () => {
    const p = paramsFromSearch(
      mkSearch('range=custom&since=2026-04-01T00:00:00Z&until=2026-04-30T23:59:59Z'),
      NOW,
    );
    expect(p.since).toBe('2026-04-01T00:00:00Z');
    expect(p.until).toBe('2026-04-30T23:59:59Z');
  });

  it('range=all yields no since and no until', () => {
    const p = paramsFromSearch(mkSearch('range=all'), NOW);
    expect(p.since).toBeUndefined();
    expect(p.until).toBeUndefined();
  });
});

describe('CLEAR_FILTERS_PATCH', () => {
  it('resets every filter key the page writes', () => {
    expect(CLEAR_FILTERS_PATCH).toEqual({
      actor: null,
      action: [],
      action_prefix: null,
      target_type: null,
      range: '7d',
      since: null,
      until: null,
    });
  });

  it('uses null (not undefined) so updateUrl removes the param entirely', () => {
    // The +page.svelte updateUrl helper treats null and "" as "delete the
    // key". Using undefined would skip the delete; using "" works but is
    // less explicit. Pin the contract.
    expect(CLEAR_FILTERS_PATCH.actor).toBeNull();
    expect(CLEAR_FILTERS_PATCH.action_prefix).toBeNull();
    expect(CLEAR_FILTERS_PATCH.since).toBeNull();
    expect(CLEAR_FILTERS_PATCH.until).toBeNull();
  });
});

describe('sortActionsByFrequency', () => {
  // A representative subset of the real ALL_AUDIT_ACTIONS list. Keeping
  // the sample small means the assertion isn't a moving target when new
  // action constants are added to api.ts.
  const SAMPLE: ReadonlyArray<AuditAction> = [
    'command.issued',
    'command.approved',
    'host.enrolled',
    'settings.user.create',
  ];

  it('orders by count desc, ties alphabetical', () => {
    const out = sortActionsByFrequency(SAMPLE, {
      'command.issued': 50,
      'command.approved': 10,
      'host.enrolled': 10,
      'settings.user.create': 0,
    });
    expect(out).toEqual([
      'command.issued', // highest count
      'command.approved', // tied with host.enrolled, alphabetically first
      'host.enrolled',
      'settings.user.create', // zero count, last
    ]);
  });

  it('treats missing keys as zero and keeps them alphabetical at the tail', () => {
    // Only one action has a recorded count; the rest fall to the back
    // in stable alphabetical order — important so the UI doesn't shuffle
    // pills around between renders on a fresh-fleet dashboard.
    const out = sortActionsByFrequency(SAMPLE, { 'host.enrolled': 3 });
    expect(out).toEqual([
      'host.enrolled',
      'command.approved',
      'command.issued',
      'settings.user.create',
    ]);
  });

  it('is pure — does not mutate the input list', () => {
    const input = [...SAMPLE];
    const snapshot = [...input];
    sortActionsByFrequency(input, { 'command.issued': 99 });
    expect(input).toEqual(snapshot);
  });
});
