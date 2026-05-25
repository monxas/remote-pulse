/**
 * Format a duration (in seconds) as a short "n unit ago" string.
 *
 * Designed for last-seen badges in the host table. Targets English; we
 * surface the full ISO timestamp via `aria-label` on the consuming
 * component so localisation and screen readers stay honest.
 */
export function formatRelative(secondsAgo: number | null | undefined): string {
  if (secondsAgo === null || secondsAgo === undefined || Number.isNaN(secondsAgo)) {
    return '—';
  }
  const s = Math.max(0, Math.floor(secondsAgo));
  if (s < 1) return 'just now';
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d ago`;
  const mo = Math.floor(d / 30);
  if (mo < 12) return `${mo}mo ago`;
  const y = Math.floor(mo / 12);
  return `${y}y ago`;
}

/** Seconds-ago from an ISO timestamp; null on bad input. */
export function secondsAgoFromIso(
  iso: string | null | undefined,
  nowMs = Date.now(),
): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return null;
  return Math.max(0, Math.floor((nowMs - t) / 1000));
}

/** Format a duration in seconds as a short uptime string ("2d 4h"). */
export function formatUptime(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds) || seconds < 0) {
    return '—';
  }
  const s = Math.floor(seconds);
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m`;
  return `${s}s`;
}
