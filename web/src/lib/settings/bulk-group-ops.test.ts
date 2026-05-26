import { describe, it, expect, vi, beforeEach } from 'vitest';

const deleteMock = vi.fn();

vi.mock('$lib/api', async () => {
  const actual = await vi.importActual<typeof import('$lib/api')>('$lib/api');
  return {
    ...actual,
    deleteSettingsGroup: (...args: unknown[]) => deleteMock(...args),
  };
});

import { ApiError } from '$lib/api';
import { bulkDeleteGroups, seedGroupItems } from './bulk-group-ops';

describe('seedGroupItems', () => {
  it('returns one pending item per group', () => {
    const items = seedGroupItems([{ name: 'prod' }, { name: 'family' }]);
    expect(items).toEqual([
      { name: 'prod', status: 'pending' },
      { name: 'family', status: 'pending' },
    ]);
  });
});

describe('bulkDeleteGroups', () => {
  beforeEach(() => deleteMock.mockReset());

  it('fires one DELETE per group and resolves with success counts', async () => {
    deleteMock.mockResolvedValue(undefined);
    const res = await bulkDeleteGroups([{ name: 'a' }, { name: 'b' }], () => {});
    expect(deleteMock).toHaveBeenCalledTimes(2);
    expect(res.okCount).toBe(2);
    expect(res.errorCount).toBe(0);
  });

  it('rewrites 409 conflict into a hosts-still-assigned message', async () => {
    deleteMock.mockImplementation(async (name: string) => {
      if (name === 'b') throw new ApiError(409, '');
    });
    const res = await bulkDeleteGroups([{ name: 'a' }, { name: 'b' }], () => {});
    expect(res.okCount).toBe(1);
    const failed = res.items.find((i) => i.name === 'b');
    expect(failed?.httpStatus).toBe(409);
    expect(failed?.error).toMatch(/hosts/);
  });
});
