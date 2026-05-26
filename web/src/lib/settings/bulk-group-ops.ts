/**
 * Bulk group mutations dispatched as N parallel requests.
 *
 * Right now the only meaningful bulk op for groups is delete (rename in
 * bulk doesn't make UX sense; bulk membership changes are driven from
 * the user side). Delete is only allowed for groups with `host_count`
 * === 0 — the server returns 409 otherwise. The UI pre-filters those
 * out before calling here so the user can't even fire a doomed batch.
 */

import { deleteSettingsGroup, ApiError, type SettingsGroup } from '$lib/api';

export type BulkGroupOpStatus = 'pending' | 'in-flight' | 'success' | 'error';

export interface BulkGroupItem {
  name: string;
  status: BulkGroupOpStatus;
  error?: string;
  httpStatus?: number;
}

export interface BulkGroupOpResult {
  items: BulkGroupItem[];
  okCount: number;
  errorCount: number;
}

function fmtError(err: unknown): { error: string; httpStatus?: number } {
  if (err instanceof ApiError) {
    if (err.status === 409)
      return {
        error: err.message || 'Group still has hosts assigned.',
        httpStatus: 409,
      };
    if (err.status === 403) return { error: 'Permission denied.', httpStatus: 403 };
    return { error: err.message, httpStatus: err.status };
  }
  return { error: err instanceof Error ? err.message : 'Unknown error.' };
}

export async function bulkDeleteGroups(
  groups: ReadonlyArray<Pick<SettingsGroup, 'name'>>,
  emit: (item: BulkGroupItem) => void,
): Promise<BulkGroupOpResult> {
  const items = await Promise.all(
    groups.map(async (g) => {
      emit({ name: g.name, status: 'in-flight' });
      try {
        await deleteSettingsGroup(g.name);
        const item: BulkGroupItem = { name: g.name, status: 'success' };
        emit(item);
        return item;
      } catch (err) {
        const { error, httpStatus } = fmtError(err);
        const item: BulkGroupItem = { name: g.name, status: 'error', error, httpStatus };
        emit(item);
        return item;
      }
    }),
  );
  return {
    items,
    okCount: items.filter((i) => i.status === 'success').length,
    errorCount: items.filter((i) => i.status === 'error').length,
  };
}

export function seedGroupItems(
  groups: ReadonlyArray<Pick<SettingsGroup, 'name'>>,
): BulkGroupItem[] {
  return groups.map((g) => ({ name: g.name, status: 'pending' as const }));
}
