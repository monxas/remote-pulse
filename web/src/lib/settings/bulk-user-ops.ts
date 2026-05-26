/**
 * Bulk user mutations dispatched as N parallel requests.
 *
 * Mirrors the rationale of `lib/commands/bulk-dispatch.ts`: the dashboard
 * backend exposes per-user endpoints (PATCH user, DELETE user, POST grant)
 * but no aggregate endpoint, and we want partial-success semantics — if
 * 3 out of 4 PATCHes succeed we should still surface that, not 4xx the
 * whole batch.
 *
 * Each operation fans out across the supplied user IDs, captures the
 * outcome per-user (success / 403 / unknown), and resolves once every
 * request has settled. The caller drives the UI from the items array.
 */

import {
  updateSettingsUser,
  deleteSettingsUser,
  grantUserPermission,
  ApiError,
  type UpdateUserInput,
  type GrantPermissionInput,
  type SettingsUser,
  type UserRole,
} from '$lib/api';

export type BulkUserOpStatus = 'pending' | 'in-flight' | 'success' | 'error';

export interface BulkUserItem {
  user_id: string;
  email: string;
  status: BulkUserOpStatus;
  error?: string;
  httpStatus?: number;
}

export interface BulkUserOpResult {
  items: BulkUserItem[];
  okCount: number;
  errorCount: number;
}

/** Map an ApiError → human-readable copy. */
function fmtError(err: unknown): { error: string; httpStatus?: number } {
  if (err instanceof ApiError) {
    if (err.status === 403) return { error: 'Permission denied.', httpStatus: 403 };
    if (err.status === 409) return { error: err.message || 'Conflict.', httpStatus: 409 };
    return { error: err.message, httpStatus: err.status };
  }
  return { error: err instanceof Error ? err.message : 'Unknown error.' };
}

async function runOne(
  user: Pick<SettingsUser, 'id' | 'email'>,
  fn: () => Promise<unknown>,
  emit: (item: BulkUserItem) => void,
): Promise<BulkUserItem> {
  emit({ user_id: user.id, email: user.email, status: 'in-flight' });
  try {
    await fn();
    const item: BulkUserItem = { user_id: user.id, email: user.email, status: 'success' };
    emit(item);
    return item;
  } catch (err) {
    const { error, httpStatus } = fmtError(err);
    const item: BulkUserItem = {
      user_id: user.id,
      email: user.email,
      status: 'error',
      error,
      httpStatus,
    };
    emit(item);
    return item;
  }
}

function summarize(items: BulkUserItem[]): BulkUserOpResult {
  return {
    items,
    okCount: items.filter((i) => i.status === 'success').length,
    errorCount: items.filter((i) => i.status === 'error').length,
  };
}

// ---- Operations --------------------------------------------------------

export type SimpleUser = Pick<SettingsUser, 'id' | 'email'>;

export async function bulkUpdateUsers(
  users: ReadonlyArray<SimpleUser>,
  input: UpdateUserInput,
  emit: (item: BulkUserItem) => void,
): Promise<BulkUserOpResult> {
  const items = await Promise.all(
    users.map((u) => runOne(u, () => updateSettingsUser(u.id, input), emit)),
  );
  return summarize(items);
}

export async function bulkDeleteUsers(
  users: ReadonlyArray<SimpleUser>,
  emit: (item: BulkUserItem) => void,
): Promise<BulkUserOpResult> {
  const items = await Promise.all(
    users.map((u) => runOne(u, () => deleteSettingsUser(u.id), emit)),
  );
  return summarize(items);
}

export async function bulkGrantPermission(
  users: ReadonlyArray<SimpleUser>,
  input: GrantPermissionInput,
  emit: (item: BulkUserItem) => void,
): Promise<BulkUserOpResult> {
  const items = await Promise.all(
    users.map((u) => runOne(u, () => grantUserPermission(u.id, input), emit)),
  );
  return summarize(items);
}

/**
 * Bulk role change with a single shared role value. Thin wrapper over
 * bulkUpdateUsers for naming clarity at the call-site.
 */
export function bulkChangeRole(
  users: ReadonlyArray<SimpleUser>,
  role: UserRole,
  emit: (item: BulkUserItem) => void,
): Promise<BulkUserOpResult> {
  return bulkUpdateUsers(users, { role }, emit);
}

/**
 * Bulk add-to-group: server's UpdateUserInput.groups is a replace-list,
 * so we read each user's current groups, union the new group, and patch.
 * We accept a `groupsById` map so the caller can pass the freshest copy
 * from the cached query without us doing another GET round-trip per user.
 */
export async function bulkAddUsersToGroup(
  users: ReadonlyArray<SettingsUser>,
  group: string,
  emit: (item: BulkUserItem) => void,
): Promise<BulkUserOpResult> {
  const items = await Promise.all(
    users.map((u) =>
      runOne(
        u,
        () => {
          const next = u.groups.includes(group) ? u.groups : [...u.groups, group];
          return updateSettingsUser(u.id, { groups: next });
        },
        emit,
      ),
    ),
  );
  return summarize(items);
}

export async function bulkRemoveUsersFromGroup(
  users: ReadonlyArray<SettingsUser>,
  group: string,
  emit: (item: BulkUserItem) => void,
): Promise<BulkUserOpResult> {
  const items = await Promise.all(
    users.map((u) =>
      runOne(
        u,
        () => {
          const next = u.groups.filter((g) => g !== group);
          return updateSettingsUser(u.id, { groups: next });
        },
        emit,
      ),
    ),
  );
  return summarize(items);
}

/** Seed for the optional progress UI. */
export function seedUserItems(users: ReadonlyArray<SimpleUser>): BulkUserItem[] {
  return users.map((u) => ({ user_id: u.id, email: u.email, status: 'pending' as const }));
}
