/**
 * Pure formatting helpers for {@link RetentionCard}.
 *
 * Extracted into a standalone module so the unit tests can exercise the
 * relative-time logic without booting the Svelte component (and the
 * window/Intl ceremony that drags in).
 */

/**
 * Render an absolute ISO timestamp as a coarse relative string.
 *
 * The audit retention card surfaces ``last_purge_at``; an admin reading
 * "purged 2 hours ago" gets more signal than "purged at 2026-05-27T03:00:00Z".
 * We deliberately stay coarse (minute / hour / day / week / month / year
 * buckets) so the string is stable across re-renders within a refresh.
 *
 * Returns ``'just now'`` for anything within the last minute, and the
 * raw ISO string for inputs we can't parse (defensive — the server's
 * Pydantic serialiser should always give us a well-formed value).
 */
export function formatRelativeTime(iso: string, now: Date = new Date()): string {
  const then = new Date(iso);
  const t = then.getTime();
  if (Number.isNaN(t)) return iso;

  const deltaMs = now.getTime() - t;
  // Future timestamps (clock skew between server + browser) collapse
  // into 'just now' — better than rendering 'in 3 seconds'.
  if (deltaMs < 0) return 'just now';

  const seconds = Math.floor(deltaMs / 1000);
  if (seconds < 60) return 'just now';

  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? '' : 's'} ago`;

  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`;

  const days = Math.floor(hours / 24);
  if (days < 7) return `${days} day${days === 1 ? '' : 's'} ago`;

  const weeks = Math.floor(days / 7);
  if (weeks < 5) return `${weeks} week${weeks === 1 ? '' : 's'} ago`;

  const months = Math.floor(days / 30);
  if (months < 12) return `${months} month${months === 1 ? '' : 's'} ago`;

  const years = Math.floor(days / 365);
  return `${years} year${years === 1 ? '' : 's'} ago`;
}
