import { describe, it, expect } from 'vitest';
import {
  DEFAULT_OPT_INS,
  classifySseEvent,
  loadOptIns,
  notificationsStorageKey,
  renderNotification,
  saveOptIns,
  shouldFireNotification,
  type NotificationOptIns,
} from './notifications-state';

/**
 * Memory-backed Storage stub good enough for the helpers we exercise
 * (only `getItem` + `setItem` are touched).
 */
function makeStorage(initial: Record<string, string> = {}): Storage {
  const data = new Map<string, string>(Object.entries(initial));
  return {
    get length() {
      return data.size;
    },
    clear: () => data.clear(),
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
    removeItem: (k: string) => void data.delete(k),
    key: (i: number) => Array.from(data.keys())[i] ?? null,
  } as Storage;
}

describe('shouldFireNotification', () => {
  const baseOptIns: NotificationOptIns = { ...DEFAULT_OPT_INS };

  it('returns false when permission is not granted', () => {
    for (const permission of ['default', 'denied', 'unsupported'] as const) {
      expect(
        shouldFireNotification({
          eventType: 'command.failed',
          optIns: baseOptIns,
          permission,
          isTabFocused: false,
        }),
      ).toBe(false);
    }
  });

  it('returns false when user opted out of this event type', () => {
    expect(
      shouldFireNotification({
        eventType: 'host.offline', // default OFF
        optIns: baseOptIns,
        permission: 'granted',
        isTabFocused: false,
      }),
    ).toBe(false);
  });

  it('returns true when granted + opted-in + tab not focused', () => {
    expect(
      shouldFireNotification({
        eventType: 'command.failed',
        optIns: baseOptIns,
        permission: 'granted',
        isTabFocused: false,
      }),
    ).toBe(true);
  });

  it('returns false when tab is focused (LiveToasts covers it)', () => {
    expect(
      shouldFireNotification({
        eventType: 'command.failed',
        optIns: baseOptIns,
        permission: 'granted',
        isTabFocused: true,
      }),
    ).toBe(false);
  });

  it('gates admin-only categories on role=admin', () => {
    const optIns: NotificationOptIns = { ...baseOptIns, 'audit.settings': true };
    expect(
      shouldFireNotification({
        eventType: 'audit.settings',
        optIns,
        permission: 'granted',
        isTabFocused: false,
        userRole: 'operator',
      }),
    ).toBe(false);
    expect(
      shouldFireNotification({
        eventType: 'audit.settings',
        optIns,
        permission: 'granted',
        isTabFocused: false,
        userRole: 'admin',
      }),
    ).toBe(true);
  });
});

describe('classifySseEvent', () => {
  it('maps failed/timeout/rejected command status to command.failed', () => {
    for (const status of ['failed', 'timeout', 'rejected']) {
      expect(classifySseEvent('command.status_change', { status })).toBe('command.failed');
    }
  });

  it('ignores successful command transitions', () => {
    expect(classifySseEvent('command.status_change', { status: 'succeeded' })).toBeNull();
  });

  it('maps approval.created and host transitions', () => {
    expect(classifySseEvent('approval.created', {})).toBe('approval.requested');
    expect(classifySseEvent('host.status_change', { to: 'offline' })).toBe('host.offline');
    expect(classifySseEvent('host.status_change', { to: 'online' })).toBe('host.online');
    expect(classifySseEvent('host.status_change', { to: 'stale' })).toBeNull();
  });

  it('maps audit events when emitted', () => {
    expect(classifySseEvent('audit.settings_change', {})).toBe('audit.settings');
    expect(classifySseEvent('audit.permission_change', {})).toBe('audit.permission');
  });

  it('returns null for unrelated event types', () => {
    expect(classifySseEvent('host.heartbeat', {})).toBeNull();
    expect(classifySseEvent('command.issued', {})).toBeNull();
    expect(classifySseEvent('gap', {})).toBeNull();
  });
});

describe('renderNotification', () => {
  it('renders command.failed with host + status + click-through URL', () => {
    const out = renderNotification(
      'command.failed',
      { hostname: 'rp-prod-1', status: 'failed', command_id: 'cmd-42', stderr: 'boom' },
      'delivery-1',
    );
    expect(out.title).toContain('rp-prod-1');
    expect(out.title).toContain('failed');
    expect(out.body).toBe('boom');
    expect(out.url).toBe('/commands/cmd-42');
    expect(out.tag).toBe('delivery-1');
  });

  it('renders approval.requested with /approvals URL', () => {
    const out = renderNotification('approval.requested', {
      hostname: 'rp-a',
      command_type: 'shell',
    });
    expect(out.title).toContain('shell');
    expect(out.url).toBe('/approvals');
  });

  it('falls back gracefully when payload fields are missing', () => {
    const out = renderNotification('host.offline', {});
    expect(out.title).toContain('a host');
    expect(out.url).toBe('/hosts');
  });
});

describe('opt-in persistence', () => {
  it('returns defaults when nothing is stored', () => {
    const storage = makeStorage();
    expect(loadOptIns(storage, 'op@x')).toEqual(DEFAULT_OPT_INS);
  });

  it('round-trips through save/load', () => {
    const storage = makeStorage();
    const opts: NotificationOptIns = {
      ...DEFAULT_OPT_INS,
      'host.offline': true,
      'command.failed': false,
    };
    saveOptIns(storage, 'op@x', opts);
    expect(loadOptIns(storage, 'op@x')).toEqual(opts);
  });

  it('namespaces storage per user email', () => {
    const storage = makeStorage();
    saveOptIns(storage, 'a@x', { ...DEFAULT_OPT_INS, 'host.offline': true });
    saveOptIns(storage, 'b@x', { ...DEFAULT_OPT_INS, 'host.offline': false });
    expect(loadOptIns(storage, 'a@x')['host.offline']).toBe(true);
    expect(loadOptIns(storage, 'b@x')['host.offline']).toBe(false);
  });

  it('falls back to defaults when storage holds garbage', () => {
    const storage = makeStorage({ [notificationsStorageKey('x@x')]: '{not valid json' });
    expect(loadOptIns(storage, 'x@x')).toEqual(DEFAULT_OPT_INS);
  });

  it('drops unknown keys and fills missing keys with defaults', () => {
    const storage = makeStorage({
      [notificationsStorageKey('x@x')]: JSON.stringify({
        'command.failed': false,
        'bogus.key': true,
      }),
    });
    const loaded = loadOptIns(storage, 'x@x');
    expect(loaded['command.failed']).toBe(false);
    expect(loaded['approval.requested']).toBe(DEFAULT_OPT_INS['approval.requested']);
    expect((loaded as Record<string, unknown>)['bogus.key']).toBeUndefined();
  });
});
