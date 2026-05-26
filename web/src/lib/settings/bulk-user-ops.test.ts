import { describe, it, expect, vi, beforeEach } from 'vitest';

const updateMock = vi.fn();
const deleteMock = vi.fn();
const grantMock = vi.fn();

vi.mock('$lib/api', async () => {
  const actual = await vi.importActual<typeof import('$lib/api')>('$lib/api');
  return {
    ...actual,
    updateSettingsUser: (...args: unknown[]) => updateMock(...args),
    deleteSettingsUser: (...args: unknown[]) => deleteMock(...args),
    grantUserPermission: (...args: unknown[]) => grantMock(...args),
  };
});

import { ApiError, type SettingsUser } from '$lib/api';
import {
  bulkChangeRole,
  bulkDeleteUsers,
  bulkGrantPermission,
  bulkAddUsersToGroup,
  bulkRemoveUsersFromGroup,
  seedUserItems,
} from './bulk-user-ops';

function mkUser(id: string, email: string, groups: string[] = []): SettingsUser {
  return {
    id,
    email,
    name: null,
    role: 'viewer',
    groups,
    is_active: true,
    created_at: new Date().toISOString(),
    last_login_at: null,
  };
}

describe('seedUserItems', () => {
  it('returns one pending item per user', () => {
    const items = seedUserItems([mkUser('u1', 'a@x'), mkUser('u2', 'b@x')]);
    expect(items).toEqual([
      { user_id: 'u1', email: 'a@x', status: 'pending' },
      { user_id: 'u2', email: 'b@x', status: 'pending' },
    ]);
  });
});

describe('bulkChangeRole', () => {
  beforeEach(() => updateMock.mockReset());

  it('fires one PATCH per user with the same role payload', async () => {
    updateMock.mockResolvedValue({});
    const users = [mkUser('u1', 'a@x'), mkUser('u2', 'b@x')];
    const events: string[] = [];
    const res = await bulkChangeRole(users, 'operator', (i) =>
      events.push(`${i.email}:${i.status}`),
    );
    expect(updateMock).toHaveBeenCalledTimes(2);
    expect(updateMock).toHaveBeenCalledWith('u1', { role: 'operator' });
    expect(updateMock).toHaveBeenCalledWith('u2', { role: 'operator' });
    expect(res.okCount).toBe(2);
    expect(res.errorCount).toBe(0);
    expect(events.filter((e) => e.endsWith(':in-flight'))).toHaveLength(2);
    expect(events.filter((e) => e.endsWith(':success'))).toHaveLength(2);
  });

  it('records partial-failure with 403 rewritten to a friendly message', async () => {
    updateMock.mockImplementation(async (id: string) => {
      if (id === 'u2') throw new ApiError(403, 'forbidden');
    });
    const res = await bulkChangeRole(
      [mkUser('u1', 'a@x'), mkUser('u2', 'b@x'), mkUser('u3', 'c@x')],
      'viewer',
      () => {},
    );
    expect(res.okCount).toBe(2);
    expect(res.errorCount).toBe(1);
    const failed = res.items.find((i) => i.user_id === 'u2');
    expect(failed?.httpStatus).toBe(403);
    expect(failed?.error).toMatch(/Permission denied/);
  });
});

describe('bulkDeleteUsers', () => {
  beforeEach(() => deleteMock.mockReset());

  it('fires one DELETE per user', async () => {
    deleteMock.mockResolvedValue(undefined);
    const res = await bulkDeleteUsers([mkUser('u1', 'a@x'), mkUser('u2', 'b@x')], () => {});
    expect(deleteMock).toHaveBeenCalledTimes(2);
    expect(res.okCount).toBe(2);
  });
});

describe('bulkGrantPermission', () => {
  beforeEach(() => grantMock.mockReset());

  it('fires one POST per user with the same grant payload', async () => {
    grantMock.mockResolvedValue({});
    await bulkGrantPermission(
      [mkUser('u1', 'a@x'), mkUser('u2', 'b@x')],
      { action: 'command.issue', scope: '*' },
      () => {},
    );
    expect(grantMock).toHaveBeenCalledTimes(2);
    expect(grantMock).toHaveBeenCalledWith('u1', { action: 'command.issue', scope: '*' });
    expect(grantMock).toHaveBeenCalledWith('u2', { action: 'command.issue', scope: '*' });
  });
});

describe('bulkAddUsersToGroup / bulkRemoveUsersFromGroup', () => {
  beforeEach(() => updateMock.mockReset());

  it("add unions the new group with the user's current groups", async () => {
    updateMock.mockResolvedValue({});
    const u1 = mkUser('u1', 'a@x', ['prod']);
    const u2 = mkUser('u2', 'b@x', ['prod', 'family']);
    await bulkAddUsersToGroup([u1, u2], 'family', () => {});
    // u1 had no family — gets it added; u2 already had it — payload unchanged
    expect(updateMock).toHaveBeenCalledWith('u1', { groups: ['prod', 'family'] });
    expect(updateMock).toHaveBeenCalledWith('u2', { groups: ['prod', 'family'] });
  });

  it("remove filters the group out, idempotent when the user didn't have it", async () => {
    updateMock.mockResolvedValue({});
    const u1 = mkUser('u1', 'a@x', ['prod', 'family']);
    const u2 = mkUser('u2', 'b@x', ['prod']);
    await bulkRemoveUsersFromGroup([u1, u2], 'family', () => {});
    expect(updateMock).toHaveBeenCalledWith('u1', { groups: ['prod'] });
    expect(updateMock).toHaveBeenCalledWith('u2', { groups: ['prod'] });
  });
});
