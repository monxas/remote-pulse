/**
 * Browser-notification opt-in state + dispatch helpers.
 *
 * ADR-0009 follow-up: operators can opt-in to native browser notifications
 * as an alternative to Telegram. We chose the **in-app SSE-driven** approach
 * (no service worker, no VAPID push, no backend changes) because it covers
 * the 90% case — the dashboard tab is open in the background — at 20% of
 * the engineering cost.
 *
 * State is persisted to `localStorage` per-user so a shared workstation
 * doesn't leak preferences between accounts. The matching helper
 * (`shouldFireNotification`) is **pure** so we can unit-test the
 * permission × opt-in × focus-state truth table without a DOM.
 */

/**
 * Notification event categories the operator can opt in/out of.
 * Keep this list in sync with `LiveNotifications.svelte` dispatch
 * and with the checkbox grid in the Settings tab.
 */
export type NotificationEventType =
  | 'command.failed'
  | 'approval.requested'
  | 'host.offline'
  | 'host.online'
  | 'audit.settings'
  | 'audit.permission';

/** Opt-in checkbox state, one boolean per event type. */
export type NotificationOptIns = Record<NotificationEventType, boolean>;

export const ALL_NOTIFICATION_EVENT_TYPES: NotificationEventType[] = [
  'command.failed',
  'approval.requested',
  'host.offline',
  'host.online',
  'audit.settings',
  'audit.permission',
];

/**
 * Defaults applied when no preference is persisted yet. We err on the side
 * of *low noise*: only the two genuinely actionable categories ship on by
 * default; the rest are opt-in.
 */
export const DEFAULT_OPT_INS: NotificationOptIns = {
  'command.failed': true,
  'approval.requested': true,
  'host.offline': false,
  'host.online': false,
  'audit.settings': false,
  'audit.permission': false,
};

/**
 * Audit-trail categories are admin-only. The Settings tab hides the row
 * if the current user lacks the role; the dispatcher also re-checks at
 * fire time so a stale localStorage from a demoted operator can't leak
 * sensitive notifications.
 */
export const ADMIN_ONLY_EVENT_TYPES = new Set<NotificationEventType>([
  'audit.settings',
  'audit.permission',
]);

export interface NotificationDecisionInput {
  /** Event category the SSE bridge mapped this event to. */
  eventType: NotificationEventType;
  /** Persisted opt-in map for the current user. */
  optIns: NotificationOptIns;
  /** Result of `Notification.permission` at decision time. */
  permission: NotificationPermission | 'unsupported';
  /** `true` when the tab is focused — in-app toast already covers it. */
  isTabFocused: boolean;
  /** Caller's role; gates admin-only categories. */
  userRole?: string | null;
}

/**
 * Pure predicate that decides whether to fire a native Notification.
 *
 * The four gates, applied in order:
 *  1. Permission must be `granted`.
 *  2. User must have opted in for this event type.
 *  3. Admin-only categories require role=admin.
 *  4. Tab must be **unfocused** — when focused, LiveToasts.svelte already
 *     surfaces a non-disruptive in-app toast and we don't want to double-fire.
 */
export function shouldFireNotification(input: NotificationDecisionInput): boolean {
  const { eventType, optIns, permission, isTabFocused, userRole } = input;
  if (permission !== 'granted') return false;
  if (!optIns[eventType]) return false;
  if (ADMIN_ONLY_EVENT_TYPES.has(eventType) && userRole !== 'admin') return false;
  if (isTabFocused) return false;
  return true;
}

/**
 * Build the per-user localStorage key. We hash on email since `user_id`
 * isn't always populated client-side until /auth/me resolves. A `null`
 * email falls back to an anonymous bucket — useful in tests.
 */
export function notificationsStorageKey(userEmail: string | null): string {
  return `rp:notifications:${userEmail ?? 'anonymous'}`;
}

/**
 * Read + merge persisted opt-ins with defaults. Defensive against
 * corrupt storage (returns defaults), missing keys (filled with defaults),
 * and unknown keys (silently dropped).
 */
export function loadOptIns(
  storage: Pick<Storage, 'getItem'>,
  userEmail: string | null,
): NotificationOptIns {
  const raw = storage.getItem(notificationsStorageKey(userEmail));
  if (!raw) return { ...DEFAULT_OPT_INS };
  try {
    const parsed = JSON.parse(raw) as Partial<NotificationOptIns>;
    const out: NotificationOptIns = { ...DEFAULT_OPT_INS };
    for (const key of ALL_NOTIFICATION_EVENT_TYPES) {
      if (typeof parsed[key] === 'boolean') {
        out[key] = parsed[key] as boolean;
      }
    }
    return out;
  } catch {
    return { ...DEFAULT_OPT_INS };
  }
}

export function saveOptIns(
  storage: Pick<Storage, 'setItem'>,
  userEmail: string | null,
  optIns: NotificationOptIns,
): void {
  storage.setItem(notificationsStorageKey(userEmail), JSON.stringify(optIns));
}

/**
 * SSE event → notification category mapper.
 *
 * Returns `null` for events that don't map to any user-visible
 * notification (heartbeats, command.issued, etc.) so the dispatcher
 * can short-circuit before touching localStorage.
 */
export function classifySseEvent(sseType: string, payload: unknown): NotificationEventType | null {
  const data = payload && typeof payload === 'object' ? (payload as Record<string, unknown>) : {};
  switch (sseType) {
    case 'command.status_change': {
      const status = typeof data.status === 'string' ? data.status : '';
      if (status === 'failed' || status === 'timeout' || status === 'rejected') {
        return 'command.failed';
      }
      return null;
    }
    case 'approval.created':
      return 'approval.requested';
    case 'host.status_change': {
      const to = typeof data.to === 'string' ? data.to : '';
      if (to === 'offline') return 'host.offline';
      if (to === 'online') return 'host.online';
      return null;
    }
    case 'audit.settings_change':
      return 'audit.settings';
    case 'audit.permission_change':
      return 'audit.permission';
    default:
      return null;
  }
}

export interface NotificationContent {
  title: string;
  body: string;
  /** Optional URL the click handler navigates to. */
  url?: string;
  /** Deduplication tag — re-fires of the same delivery collapse in-tray. */
  tag?: string;
}

/**
 * Render a friendly title + body for a given event category. The dispatcher
 * passes this directly to the `Notification` constructor.
 */
export function renderNotification(
  eventType: NotificationEventType,
  payload: unknown,
  deliveryId?: string | null,
): NotificationContent {
  const data = payload && typeof payload === 'object' ? (payload as Record<string, unknown>) : {};
  const readString = (key: string): string | null => {
    const v = data[key];
    return typeof v === 'string' && v.length > 0 ? v : null;
  };
  const host =
    readString('hostname') ?? readString('host_hostname') ?? readString('host_id') ?? 'a host';
  const tag = deliveryId ?? undefined;

  switch (eventType) {
    case 'command.failed': {
      const status = readString('status') ?? 'failed';
      const commandId = readString('command_id');
      return {
        title: `Command ${status} on ${host}`,
        body: readString('stderr') ?? `Exit ${readString('exit_code') ?? status}`,
        url: commandId ? `/commands/${commandId}` : undefined,
        tag,
      };
    }
    case 'approval.requested': {
      const cmd = readString('command_type') ?? readString('action') ?? 'Command';
      return {
        title: `Approval needed for ${cmd}`,
        body: `Pending on ${host}.`,
        url: '/approvals',
        tag,
      };
    }
    case 'host.offline': {
      const hostId = readString('host_id');
      return {
        title: `${host} went offline`,
        body: 'No heartbeat received within the offline threshold.',
        url: hostId ? `/hosts/${hostId}` : '/hosts',
        tag,
      };
    }
    case 'host.online': {
      const hostId = readString('host_id');
      return {
        title: `${host} is back online`,
        body: 'Heartbeat resumed.',
        url: hostId ? `/hosts/${hostId}` : '/hosts',
        tag,
      };
    }
    case 'audit.settings': {
      const actor = readString('actor') ?? 'someone';
      return {
        title: 'Settings changed',
        body: `${actor} updated dashboard settings.`,
        url: '/audit',
        tag,
      };
    }
    case 'audit.permission': {
      const actor = readString('actor') ?? 'someone';
      return {
        title: 'Permission changed',
        body: `${actor} updated a permission grant.`,
        url: '/audit',
        tag,
      };
    }
  }
}

/** Human-readable labels for the Settings checkboxes. */
export const EVENT_TYPE_LABELS: Record<NotificationEventType, string> = {
  'command.failed': 'Command failed',
  'approval.requested': 'Approval requested',
  'host.offline': 'Host went offline',
  'host.online': 'Host came back online',
  'audit.settings': 'Settings change (audit)',
  'audit.permission': 'Permission grant/revoke (audit)',
};
