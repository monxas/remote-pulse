/**
 * Unit tests for the optimistic-update patch helpers.
 *
 * These run in pure node (no DOM, no svelte-query) because the helpers
 * are deliberately pure functions: they take the cached payload + the
 * mutation input and return the next cached payload. That keeps the
 * `onMutate` handlers in `queries/index.ts` short and gives us cheap
 * coverage of the patch logic without spinning up a QueryClient.
 */
import { describe, it, expect } from 'vitest';
import {
  patchGroupsAfterCreate,
  patchGroupsAfterDelete,
  patchHostsAfterDelete,
  patchPermissionsAfterGrant,
  patchPermissionsAfterRevoke,
  patchUsersAfterCreate,
  patchUsersAfterDelete,
  patchUsersAfterUpdate,
} from './index';
import type {
  HostsList,
  SettingsGroupsResponse,
  SettingsUsersResponse,
  UserPermissionsResponse,
} from '$lib/api';

describe('patchGroupsAfterCreate', () => {
  it('appends a zero-count placeholder while preserving existing rows', () => {
    const old: SettingsGroupsResponse = {
      groups: [
        {
          name: 'prod',
          description: 'Production',
          host_count: 3,
          user_count: 2,
          auto_distribute_keys: true,
          created_at: '2026-01-01T00:00:00Z',
        },
      ],
    };
    const next = patchGroupsAfterCreate(old, { name: 'stage', description: null });
    expect(next.groups).toHaveLength(2);
    expect(next.groups[0]?.name).toBe('prod'); // existing kept
    expect(next.groups[1]).toMatchObject({
      name: 'stage',
      host_count: 0,
      user_count: 0,
      auto_distribute_keys: true,
    });
  });

  it('handles an undefined cache as an empty list', () => {
    const next = patchGroupsAfterCreate(undefined, { name: 'alpha' });
    expect(next.groups).toHaveLength(1);
    expect(next.groups[0]?.name).toBe('alpha');
  });
});

describe('patchGroupsAfterDelete', () => {
  it('removes the named group and leaves the rest alone', () => {
    const old: SettingsGroupsResponse = {
      groups: [
        {
          name: 'prod',
          description: null,
          host_count: 0,
          user_count: 0,
          auto_distribute_keys: true,
          created_at: '2026-01-01T00:00:00Z',
        },
        {
          name: 'stage',
          description: null,
          host_count: 0,
          user_count: 0,
          auto_distribute_keys: true,
          created_at: '2026-01-01T00:00:00Z',
        },
      ],
    };
    expect(patchGroupsAfterDelete(old, 'stage').groups.map((g) => g.name)).toEqual(['prod']);
  });
});

describe('patchUsersAfterCreate', () => {
  it('prepends an optimistic placeholder with a stable optimistic id', () => {
    const next = patchUsersAfterCreate(undefined, {
      email: 'new@test.local',
      name: 'New',
      role: 'operator',
      groups: ['prod'],
    });
    expect(next.users).toHaveLength(1);
    expect(next.users[0]?.email).toBe('new@test.local');
    expect(next.users[0]?.id.startsWith('optimistic-')).toBe(true);
    expect(next.users[0]?.is_active).toBe(true);
  });
});

describe('patchUsersAfterUpdate', () => {
  const base: SettingsUsersResponse = {
    users: [
      {
        id: 'u-1',
        email: 'a@b',
        name: null,
        role: 'viewer',
        groups: [],
        is_active: true,
        created_at: '2026-01-01T00:00:00Z',
        last_login_at: null,
      },
    ],
  };

  it('only patches the matching id', () => {
    const next = patchUsersAfterUpdate(base, 'u-1', { role: 'operator' });
    expect(next.users[0]?.role).toBe('operator');
    expect(next.users[0]?.groups).toEqual([]); // untouched
  });

  it('leaves non-matching users alone', () => {
    const next = patchUsersAfterUpdate(base, 'someone-else', { role: 'admin' });
    expect(next.users[0]?.role).toBe('viewer');
  });

  it('passes through groups + is_active when provided', () => {
    const next = patchUsersAfterUpdate(base, 'u-1', {
      groups: ['prod'],
      is_active: false,
    });
    expect(next.users[0]?.groups).toEqual(['prod']);
    expect(next.users[0]?.is_active).toBe(false);
  });
});

describe('patchUsersAfterDelete', () => {
  it('removes the user with the matching id', () => {
    const next = patchUsersAfterDelete(
      {
        users: [
          {
            id: 'u-1',
            email: 'a@b',
            name: null,
            role: 'viewer',
            groups: [],
            is_active: true,
            created_at: '',
            last_login_at: null,
          },
        ],
      },
      'u-1',
    );
    expect(next.users).toHaveLength(0);
  });
});

describe('patchPermissionsAfterGrant', () => {
  it('prepends an optimistic permission and preserves allowed_actions', () => {
    const old: UserPermissionsResponse = {
      permissions: [],
      allowed_actions: ['command.issue', 'command.approve'],
    };
    const next = patchPermissionsAfterGrant(
      old,
      'user-42',
      { action: 'command.issue', scope: 'prod' },
      'admin@test.local',
    );
    expect(next.permissions).toHaveLength(1);
    expect(next.permissions[0]).toMatchObject({
      user_id: 'user-42',
      action: 'command.issue',
      scope: 'prod',
      granted_by: 'admin@test.local',
    });
    expect(next.allowed_actions).toEqual(['command.issue', 'command.approve']);
  });
});

describe('patchPermissionsAfterRevoke', () => {
  it('removes the permission with the matching id', () => {
    const old: UserPermissionsResponse = {
      permissions: [
        {
          id: 'p-1',
          user_id: 'u-1',
          action: 'command.issue',
          scope: '*',
          granted_by: 'admin@test.local',
          granted_at: '2026-01-01T00:00:00Z',
        },
        {
          id: 'p-2',
          user_id: 'u-1',
          action: 'host.delete',
          scope: 'prod',
          granted_by: 'admin@test.local',
          granted_at: '2026-01-01T00:00:00Z',
        },
      ],
      allowed_actions: [],
    };
    const next = patchPermissionsAfterRevoke(old, 'p-1');
    expect(next.permissions.map((p) => p.id)).toEqual(['p-2']);
  });
});

describe('patchHostsAfterDelete', () => {
  const sampleHost = (id: string, hostname: string): HostsList['hosts'][number] => ({
    id,
    hostname,
    group_name: 'prod',
    status: 'online',
    last_seen_at: '2026-05-26T00:00:00Z',
    last_seen_seconds_ago: 3,
    os_family: 'linux',
    agent_version: '1.0.8',
    tailscale_ip: '100.64.0.10',
    current: { cpu_pct: 10, mem_pct: 40, load_1m: 0.2, uptime_s: 3600 },
    sparkline: { window_s: 60, bucket_s: 10, ts: [], cpu_pct: [], mem_pct: [] },
  });

  it('removes the host with the given id and keeps the rest', () => {
    const old: HostsList = {
      hosts: [
        sampleHost('host-a', 'rp-a'),
        sampleHost('host-b', 'rp-b'),
        sampleHost('host-c', 'rp-c'),
      ],
      groups: ['prod'],
    };
    const next = patchHostsAfterDelete(old, 'host-b');
    expect(next.hosts.map((h) => h.id)).toEqual(['host-a', 'host-c']);
    expect(next.groups).toEqual(['prod']);
  });

  it('is a no-op when the host id is not in the list', () => {
    const old: HostsList = {
      hosts: [sampleHost('host-a', 'rp-a')],
      groups: ['prod'],
    };
    const next = patchHostsAfterDelete(old, 'host-missing');
    expect(next.hosts.map((h) => h.id)).toEqual(['host-a']);
  });

  it('handles an undefined cache as an empty list + empty groups', () => {
    const next = patchHostsAfterDelete(undefined, 'host-a');
    expect(next.hosts).toEqual([]);
    expect(next.groups).toEqual([]);
  });
});
