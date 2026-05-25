import { describe, it, expect } from 'vitest';
import { formatRelative, secondsAgoFromIso, formatUptime } from './relative-time';

describe('formatRelative', () => {
  it('handles null/undefined/NaN', () => {
    expect(formatRelative(null)).toBe('—');
    expect(formatRelative(undefined)).toBe('—');
    expect(formatRelative(Number.NaN)).toBe('—');
  });

  it('renders sub-second as "just now"', () => {
    expect(formatRelative(0)).toBe('just now');
    expect(formatRelative(0.4)).toBe('just now');
  });

  it('renders seconds', () => {
    expect(formatRelative(1)).toBe('1s ago');
    expect(formatRelative(59)).toBe('59s ago');
  });

  it('renders minutes', () => {
    expect(formatRelative(60)).toBe('1m ago');
    expect(formatRelative(125)).toBe('2m ago');
    expect(formatRelative(60 * 59)).toBe('59m ago');
  });

  it('renders hours', () => {
    expect(formatRelative(60 * 60)).toBe('1h ago');
    expect(formatRelative(60 * 60 * 23)).toBe('23h ago');
  });

  it('renders days', () => {
    expect(formatRelative(60 * 60 * 24)).toBe('1d ago');
    expect(formatRelative(60 * 60 * 24 * 29)).toBe('29d ago');
  });

  it('renders months', () => {
    expect(formatRelative(60 * 60 * 24 * 30)).toBe('1mo ago');
  });

  it('renders years', () => {
    expect(formatRelative(60 * 60 * 24 * 30 * 12)).toBe('1y ago');
  });

  it('clamps negative input to zero', () => {
    expect(formatRelative(-5)).toBe('just now');
  });
});

describe('secondsAgoFromIso', () => {
  it('returns null for null / undefined / empty', () => {
    expect(secondsAgoFromIso(null)).toBe(null);
    expect(secondsAgoFromIso(undefined)).toBe(null);
    expect(secondsAgoFromIso('')).toBe(null);
  });

  it('returns null for bad timestamps', () => {
    expect(secondsAgoFromIso('not-a-date')).toBe(null);
  });

  it('computes seconds since a fixed iso', () => {
    const now = Date.parse('2025-01-01T00:01:30Z');
    expect(secondsAgoFromIso('2025-01-01T00:01:00Z', now)).toBe(30);
  });
});

describe('formatUptime', () => {
  it('handles invalid input', () => {
    expect(formatUptime(null)).toBe('—');
    expect(formatUptime(undefined)).toBe('—');
    expect(formatUptime(-1)).toBe('—');
    expect(formatUptime(Number.NaN)).toBe('—');
  });

  it('formats seconds-only', () => {
    expect(formatUptime(0)).toBe('0s');
    expect(formatUptime(45)).toBe('45s');
  });

  it('formats minutes', () => {
    expect(formatUptime(60)).toBe('1m');
    expect(formatUptime(60 * 30)).toBe('30m');
  });

  it('formats hours and minutes', () => {
    expect(formatUptime(60 * 60 + 60 * 5)).toBe('1h 5m');
  });

  it('formats days and hours', () => {
    expect(formatUptime(60 * 60 * 24 * 2 + 60 * 60 * 4)).toBe('2d 4h');
  });
});
