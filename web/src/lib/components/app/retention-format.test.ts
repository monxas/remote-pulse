import { describe, it, expect } from 'vitest';
import { formatRelativeTime } from './retention-format';

describe('formatRelativeTime', () => {
  // Fixed "now" so every assertion is deterministic regardless of
  // when the suite runs.
  const now = new Date('2026-05-27T12:00:00Z');

  it('returns "just now" for sub-minute deltas', () => {
    expect(formatRelativeTime('2026-05-27T11:59:30Z', now)).toBe('just now');
    expect(formatRelativeTime('2026-05-27T12:00:00Z', now)).toBe('just now');
  });

  it('clamps future timestamps (clock skew) to "just now"', () => {
    expect(formatRelativeTime('2026-05-27T12:05:00Z', now)).toBe('just now');
  });

  it('renders minutes', () => {
    expect(formatRelativeTime('2026-05-27T11:58:00Z', now)).toBe('2 minutes ago');
    expect(formatRelativeTime('2026-05-27T11:59:00Z', now)).toBe('1 minute ago');
  });

  it('renders hours', () => {
    expect(formatRelativeTime('2026-05-27T10:00:00Z', now)).toBe('2 hours ago');
    expect(formatRelativeTime('2026-05-27T11:00:00Z', now)).toBe('1 hour ago');
  });

  it('renders days', () => {
    expect(formatRelativeTime('2026-05-26T12:00:00Z', now)).toBe('1 day ago');
    expect(formatRelativeTime('2026-05-24T12:00:00Z', now)).toBe('3 days ago');
  });

  it('renders weeks', () => {
    expect(formatRelativeTime('2026-05-20T12:00:00Z', now)).toBe('1 week ago');
  });

  it('renders months', () => {
    expect(formatRelativeTime('2026-03-27T12:00:00Z', now)).toBe('2 months ago');
  });

  it('renders years for very old timestamps', () => {
    expect(formatRelativeTime('2023-05-27T12:00:00Z', now)).toBe('3 years ago');
  });

  it('returns the raw string for unparseable input', () => {
    expect(formatRelativeTime('not-a-date', now)).toBe('not-a-date');
  });
});
