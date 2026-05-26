import { describe, it, expect } from 'vitest';
import { __testing, ALL_AUDIT_ACTIONS, ALL_COMMAND_STATUSES, buildAuditExportUrl } from './api';

const { buildCommandsQuery, buildAuditQuery } = __testing;

describe('buildCommandsQuery', () => {
  it('returns an empty string for no params', () => {
    expect(buildCommandsQuery({})).toBe('');
  });

  it('repeats the status key for each value', () => {
    const qs = buildCommandsQuery({ status: ['running', 'failed'] });
    // URLSearchParams.toString preserves insertion order:
    expect(qs).toBe('?status=running&status=failed');
  });

  it('omits the status param entirely when empty', () => {
    expect(buildCommandsQuery({ status: [] })).toBe('');
  });

  it('passes through host_id, issued_by, limit, cursor', () => {
    const qs = buildCommandsQuery({
      host_id: 'h-1',
      issued_by: 'alice',
      limit: 25,
      cursor: 'abc',
    });
    const parsed = new URLSearchParams(qs.slice(1));
    expect(parsed.get('host_id')).toBe('h-1');
    expect(parsed.get('issued_by')).toBe('alice');
    expect(parsed.get('limit')).toBe('25');
    expect(parsed.get('cursor')).toBe('abc');
  });

  it('emits limit=0 when explicitly zero (operator intent)', () => {
    const qs = buildCommandsQuery({ limit: 0 });
    expect(qs).toBe('?limit=0');
  });
});

describe('buildAuditQuery', () => {
  it('returns an empty string for no params', () => {
    expect(buildAuditQuery({})).toBe('');
  });

  it('repeats the action key for each value', () => {
    const qs = buildAuditQuery({ action: ['command.issued', 'command.failed'] });
    expect(qs).toBe('?action=command.issued&action=command.failed');
  });

  it('serialises every supported scalar param', () => {
    const qs = buildAuditQuery({
      actor: 'alice',
      target_type: 'command',
      since: '2026-01-01T00:00:00Z',
      until: '2026-02-01T00:00:00Z',
      limit: 50,
      cursor: 'opaque',
    });
    const parsed = new URLSearchParams(qs.slice(1));
    expect(parsed.get('actor')).toBe('alice');
    expect(parsed.get('target_type')).toBe('command');
    expect(parsed.get('since')).toBe('2026-01-01T00:00:00Z');
    expect(parsed.get('until')).toBe('2026-02-01T00:00:00Z');
    expect(parsed.get('limit')).toBe('50');
    expect(parsed.get('cursor')).toBe('opaque');
  });

  it('omits empty action arrays', () => {
    expect(buildAuditQuery({ action: [] })).toBe('');
  });

  it('serialises action_prefix as a scalar param', () => {
    const qs = buildAuditQuery({ action_prefix: 'settings.' });
    expect(qs).toBe('?action_prefix=settings.');
  });

  it('round-trips cursor pagination — page 1 has no cursor, page 2 carries one', () => {
    // Simulate svelte-query's pagination contract for the infinite query:
    // the first fetch sends no cursor, the next fetch sends the cursor we
    // received from the previous page. The server contract requires the
    // cursor to be passed through as `?cursor=<opaque>`.
    const page1 = buildAuditQuery({ limit: 100 });
    expect(page1).toBe('?limit=100');
    const page2 = buildAuditQuery({ limit: 100, cursor: 'eyJ0cyI6MTIzNH0=' });
    expect(page2).toBe('?limit=100&cursor=eyJ0cyI6MTIzNH0%3D');
  });
});

describe('buildAuditExportUrl', () => {
  it('defaults to CSV when format is omitted', () => {
    expect(buildAuditExportUrl({})).toBe('/v1/dash/audit/export?format=csv');
  });

  it('honours format=json', () => {
    expect(buildAuditExportUrl({}, 'json')).toBe('/v1/dash/audit/export?format=json');
  });

  it('applies filter params and strips cursor/limit', () => {
    const url = buildAuditExportUrl(
      {
        actor: 'alice',
        action: ['command.issued'],
        action_prefix: undefined,
        target_type: 'command',
        since: '2026-01-01T00:00:00Z',
        cursor: 'opaque-cursor',
        limit: 50,
      },
      'csv',
    );
    const [path, qs] = url.split('?');
    expect(path).toBe('/v1/dash/audit/export');
    const parsed = new URLSearchParams(qs);
    expect(parsed.get('actor')).toBe('alice');
    expect(parsed.get('action')).toBe('command.issued');
    expect(parsed.get('target_type')).toBe('command');
    expect(parsed.get('since')).toBe('2026-01-01T00:00:00Z');
    expect(parsed.get('format')).toBe('csv');
    // Cursor + limit are stripped — export ignores both.
    expect(parsed.get('cursor')).toBeNull();
    expect(parsed.get('limit')).toBeNull();
  });
});

describe('catalogue constants', () => {
  it('exposes nine command statuses', () => {
    expect(ALL_COMMAND_STATUSES.length).toBe(9);
  });
  it('exposes fourteen audit actions', () => {
    // 12 baseline (commands x5, host.enrolled, enrollment.token_issued,
    // settings.{group,user}.*) + 2 new permission grants (grant/revoke).
    expect(ALL_AUDIT_ACTIONS.length).toBe(14);
  });
});
