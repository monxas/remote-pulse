/**
 * Typed query hooks for the Phase-1/Phase-2 dashboard.
 *
 * svelte-query v5 accepts either a static options object or a Svelte
 * `Readable<options>`. To stay reactive against Svelte 5 runes that live
 * in components, we expose helpers that consume a Svelte `Readable<Params>`
 * (the caller wires the readable to runes inside a `$effect`).
 *
 * Query keys are namespaced so the SSE invalidator can target precisely:
 *   ['overview']                          -> /v1/dash/overview
 *   ['hosts', params?]                    -> /v1/dash/hosts
 *   ['host', id]                          -> single host (derived)
 *   ['timeseries', id, params]            -> /v1/dash/hosts/:id/timeseries
 *   ['commands', params]                  -> /v1/dash/commands (infinite)
 *   ['commands', id]                      -> /v1/dash/commands/:id
 *   ['approvals', 'pending']              -> /v1/dash/approvals/pending
 *   ['audit', params]                     -> /v1/dash/audit (infinite)
 */

import { derived, readable, type Readable } from 'svelte/store';
import {
  createInfiniteQuery,
  createMutation,
  createQuery,
  useQueryClient,
} from '@tanstack/svelte-query';
import { toast } from 'svelte-sonner';
import {
  approveDashCommand,
  createEnrollLink,
  createSettingsGroup,
  createSettingsUser,
  createWebhook,
  deleteHost,
  deleteSettingsGroup,
  deleteSettingsUser,
  deleteWebhook,
  getDashAudit,
  getDashCommand,
  getDashCommands,
  getDashHosts,
  getDashOverview,
  getDashPendingApprovals,
  getDashStats,
  getDashTimeseries,
  getEnrollLinks,
  getSettingsGroups,
  getSettingsUsers,
  getWebhooks,
  grantUserPermission,
  IN_FLIGHT_STATUSES,
  issueDashCommand,
  listUserPermissions,
  rejectDashCommand,
  retryDashCommand,
  revokeEnrollLink,
  revokeUserPermission,
  testWebhook,
  updateSettingsUser,
  updateWebhook,
  type AuditListPage,
  type AuditQueryParams,
  type CommandRecord,
  type CommandsListPage,
  type CommandsQueryParams,
  type CreateGroupInput,
  type CreateUserInput,
  type DashOverview,
  type DashStats,
  type EnrollLinkCreateInput,
  type EnrollLinkListResponse,
  type EnrollLinkOut,
  type GrantPermissionInput,
  type HostStatus,
  type HostsList,
  type HostSummary,
  type IssueCommandInput,
  type PendingApprovalsResponse,
  type SettingsGroup,
  type SettingsGroupsResponse,
  type SettingsUser,
  type SettingsUsersResponse,
  type StatsRange,
  type TimeseriesPayload,
  type UpdateUserInput,
  type UserPermission,
  type UserPermissionsResponse,
  type CreateWebhookInput,
  type UpdateWebhookInput,
  type WebhookCreateResponse,
  type WebhookListResponse,
  type WebhookSummary,
} from '$lib/api';

// ---- query keys ----
export const qk = {
  overview: () => ['overview'] as const,
  hosts: (params: HostsParams = {}) => ['hosts', params] as const,
  hostsAll: () => ['hosts'] as const,
  host: (hostId: string) => ['host', hostId] as const,
  timeseries: (hostId: string, params: TimeseriesParams) => ['timeseries', hostId, params] as const,
  commandsList: (params: CommandsQueryParams = {}) => ['commands', 'list', params] as const,
  commandsAll: () => ['commands'] as const,
  command: (id: string) => ['commands', 'detail', id] as const,
  approvalsPending: () => ['approvals', 'pending'] as const,
  approvalsAll: () => ['approvals'] as const,
  auditList: (params: AuditQueryParams = {}) => ['audit', 'list', params] as const,
  auditAll: () => ['audit'] as const,
  settingsGroups: () => ['settings', 'groups'] as const,
  settingsUsers: () => ['settings', 'users'] as const,
  settingsUserPermissions: (userId: string) =>
    ['settings', 'users', userId, 'permissions'] as const,
  settingsAll: () => ['settings'] as const,
  enrollLinks: () => ['enroll', 'links'] as const,
  enrollAll: () => ['enroll'] as const,
  stats: (range: StatsRange) => ['stats', range] as const,
  webhooks: () => ['webhooks'] as const,
} as const;

export interface HostsParams {
  group?: string;
  status?: HostStatus;
  q?: string;
  window?: string;
}

export interface TimeseriesParams {
  window: string;
  series: string[];
}

// ---- /v1/dash/stats ----
export function createStatsQuery(range: Readable<StatsRange>) {
  return createQuery<DashStats>(
    derived(range, (r) => ({
      queryKey: qk.stats(r),
      queryFn: ({ signal }: { signal: AbortSignal }) => getDashStats(r, undefined, signal),
      // Aggregations don't need sub-second freshness; refetch every
      // minute so users on the page see new commands trickle in.
      refetchInterval: 60_000,
      staleTime: 30_000,
    })),
  );
}

// ---- /v1/dash/overview ----
export function createOverviewQuery() {
  return createQuery<DashOverview>({
    queryKey: qk.overview(),
    queryFn: ({ signal }) => getDashOverview(undefined, signal),
    refetchInterval: 5_000,
    staleTime: 10_000,
  });
}

// ---- /v1/dash/hosts ----
export function createHostsQuery(params: Readable<HostsParams>) {
  return createQuery<HostsList>(
    derived(params, (p) => ({
      queryKey: qk.hosts(p),
      queryFn: ({ signal }: { signal: AbortSignal }) => getDashHosts(p, undefined, signal),
      refetchInterval: 5_000,
      staleTime: 10_000,
    })),
  );
}

// ---- single-host view ----
export function createHostDetailQuery(hostId: Readable<string>) {
  return createQuery<HostSummary | undefined>(
    derived(hostId, (id) => ({
      queryKey: qk.host(id),
      queryFn: async ({ signal }: { signal: AbortSignal }): Promise<HostSummary | undefined> => {
        const { hosts } = await getDashHosts({}, undefined, signal);
        return hosts.find((h) => h.id === id);
      },
      refetchInterval: 5_000,
      staleTime: 10_000,
      enabled: id.length > 0,
    })),
  );
}

// ---- /v1/dash/hosts/:id/timeseries ----
export function createTimeseriesQuery(
  hostId: Readable<string>,
  params: Readable<TimeseriesParams>,
) {
  const combined = derived([hostId, params], ([id, p]) => ({ id, p }));
  return createQuery<TimeseriesPayload>(
    derived(combined, ({ id, p }) => ({
      queryKey: qk.timeseries(id, p),
      queryFn: ({ signal }: { signal: AbortSignal }) => getDashTimeseries(id, p, undefined, signal),
      refetchInterval: false as const,
      staleTime: 30_000,
      enabled: id.length > 0 && p.series.length > 0,
    })),
  );
}

// ---- /v1/dash/commands (infinite list) ----
export function createCommandsQuery(params: Readable<CommandsQueryParams>) {
  return createInfiniteQuery<
    CommandsListPage,
    Error,
    { pages: CommandsListPage[]; pageParams: (string | undefined)[] },
    ReturnType<typeof qk.commandsList>,
    string | undefined
  >(
    derived(params, (p) => ({
      queryKey: qk.commandsList(p),
      queryFn: ({ pageParam, signal }: { pageParam: string | undefined; signal: AbortSignal }) =>
        getDashCommands({ ...p, cursor: pageParam ?? undefined }, undefined, signal),
      initialPageParam: undefined as string | undefined,
      getNextPageParam: (last: CommandsListPage) => last.next_cursor ?? undefined,
      staleTime: 5_000,
    })),
  );
}

// ---- single command (polls when in flight) ----
export function createCommandDetailQuery(commandId: Readable<string>) {
  return createQuery<CommandRecord>(
    derived(commandId, (id) => ({
      queryKey: qk.command(id),
      queryFn: ({ signal }: { signal: AbortSignal }) => getDashCommand(id, undefined, signal),
      enabled: id.length > 0,
      // Poll every 3s while the command is still moving through the
      // lifecycle. Steady-state finishes are static, no need to refetch.
      refetchInterval: (q: { state: { data: CommandRecord | undefined } }) => {
        const data = q.state.data;
        if (!data) return 3_000;
        return IN_FLIGHT_STATUSES.has(data.status) ? 3_000 : false;
      },
      staleTime: 1_000,
    })),
  );
}

// ---- /v1/dash/approvals/pending ----
export function createPendingApprovalsQuery() {
  return createQuery<PendingApprovalsResponse>({
    queryKey: qk.approvalsPending(),
    queryFn: ({ signal }) => getDashPendingApprovals(undefined, signal),
    refetchInterval: 10_000,
    staleTime: 5_000,
  });
}

// ---- /v1/dash/audit (infinite list) ----
export function createAuditQuery(params: Readable<AuditQueryParams>) {
  return createInfiniteQuery<
    AuditListPage,
    Error,
    { pages: AuditListPage[]; pageParams: (string | undefined)[] },
    ReturnType<typeof qk.auditList>,
    string | undefined
  >(
    derived(params, (p) => ({
      queryKey: qk.auditList(p),
      queryFn: ({ pageParam, signal }: { pageParam: string | undefined; signal: AbortSignal }) =>
        getDashAudit({ ...p, cursor: pageParam ?? undefined }, undefined, signal),
      initialPageParam: undefined as string | undefined,
      getNextPageParam: (last: AuditListPage) => last.next_cursor ?? undefined,
      staleTime: 5_000,
    })),
  );
}

// ---- Mutations ----

/** Issue one or more commands. Invalidates command + audit lists on success. */
export function createIssueCommandMutation() {
  const client = useQueryClient();
  return createMutation({
    mutationFn: (input: IssueCommandInput) => issueDashCommand(input),
    onSuccess: (data) => {
      const n = data.commands.length;
      toast.success(n === 1 ? 'Command issued' : `Issued ${n} commands`);
      void client.invalidateQueries({ queryKey: qk.commandsAll() });
      void client.invalidateQueries({ queryKey: qk.auditAll() });
      void client.invalidateQueries({ queryKey: qk.overview() });
      if (data.commands.some((c) => c.status === 'pending-approval')) {
        void client.invalidateQueries({ queryKey: qk.approvalsAll() });
      }
    },
    onError: (err: Error) => {
      toast.error('Could not issue command', { description: err.message });
    },
  });
}

/** Retry a finished or failed command (server clones + re-queues). */
export function createRetryCommandMutation() {
  const client = useQueryClient();
  return createMutation({
    mutationFn: (id: string) => retryDashCommand(id),
    onSuccess: (cmd) => {
      toast.success('Command re-issued');
      void client.invalidateQueries({ queryKey: qk.commandsAll() });
      void client.invalidateQueries({ queryKey: qk.command(cmd.id) });
      void client.invalidateQueries({ queryKey: qk.auditAll() });
    },
    onError: (err: Error) => {
      toast.error('Retry failed', { description: err.message });
    },
  });
}

/** Approve a pending command. */
export function createApproveMutation() {
  const client = useQueryClient();
  return createMutation({
    mutationFn: (id: string) => approveDashCommand(id),
    onSuccess: (resp) => {
      toast.success('Approved');
      void client.invalidateQueries({ queryKey: qk.approvalsAll() });
      void client.invalidateQueries({ queryKey: qk.commandsAll() });
      void client.invalidateQueries({ queryKey: qk.command(resp.command.id) });
      void client.invalidateQueries({ queryKey: qk.auditAll() });
      void client.invalidateQueries({ queryKey: qk.overview() });
    },
    onError: (err: Error) => {
      toast.error('Approve failed', { description: err.message });
    },
  });
}

/** Reject a pending command with a reason. */
export function createRejectMutation() {
  const client = useQueryClient();
  return createMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) => rejectDashCommand(id, reason),
    onSuccess: (resp) => {
      toast.success('Rejected');
      void client.invalidateQueries({ queryKey: qk.approvalsAll() });
      void client.invalidateQueries({ queryKey: qk.commandsAll() });
      void client.invalidateQueries({ queryKey: qk.command(resp.command.id) });
      void client.invalidateQueries({ queryKey: qk.auditAll() });
      void client.invalidateQueries({ queryKey: qk.overview() });
    },
    onError: (err: Error) => {
      toast.error('Reject failed', { description: err.message });
    },
  });
}

// ---- /v1/dash/settings/* (ADR-0009 Phase 4) ----

export function createSettingsGroupsQuery() {
  return createQuery<SettingsGroupsResponse>({
    queryKey: qk.settingsGroups(),
    queryFn: ({ signal }) => getSettingsGroups(undefined, signal),
    staleTime: 30_000,
  });
}

export function createSettingsUsersQuery() {
  return createQuery<SettingsUsersResponse>({
    queryKey: qk.settingsUsers(),
    queryFn: ({ signal }) => getSettingsUsers(undefined, signal),
    staleTime: 30_000,
  });
}

// ---- Optimistic mutation helpers --------------------------------------- //
//
// All Settings mutations share the same shape:
//   1. cancel in-flight refetches for the affected list so they don't
//      stomp our optimistic update,
//   2. snapshot the previous cache as the rollback target,
//   3. patch the cache to reflect the pending change,
//   4. on error -> restore the snapshot + surface a toast,
//   5. on settle -> invalidate so the server's truth wins eventually.
//
// The patch helpers are pure functions exported for vitest coverage; they
// take the raw cached payload (`old`) and the mutation input, and return
// the next payload with the change applied. Keeping them pure means the
// `onMutate` body stays tiny and we can unit-test the diff in isolation.

export function patchGroupsAfterCreate(
  old: SettingsGroupsResponse | undefined,
  input: CreateGroupInput,
): SettingsGroupsResponse {
  const placeholder: SettingsGroup = {
    name: input.name,
    description: input.description ?? null,
    host_count: 0,
    user_count: 0,
    auto_distribute_keys: true,
    created_at: _nowIso(),
  };
  return { groups: [...(old?.groups ?? []), placeholder] };
}

export function patchGroupsAfterDelete(
  old: SettingsGroupsResponse | undefined,
  name: string,
): SettingsGroupsResponse {
  return { groups: (old?.groups ?? []).filter((g) => g.name !== name) };
}

export function patchUsersAfterCreate(
  old: SettingsUsersResponse | undefined,
  input: CreateUserInput,
): SettingsUsersResponse {
  // Placeholder id so the {#each} key tracking stays happy until the
  // server response replaces the optimistic row on invalidation.
  const placeholder: SettingsUser = {
    id: `optimistic-${input.email}-${Date.now()}`,
    email: input.email,
    name: input.name ?? null,
    role: input.role,
    groups: input.groups,
    is_active: true,
    created_at: _nowIso(),
    last_login_at: null,
  };
  return { users: [placeholder, ...(old?.users ?? [])] };
}

export function patchUsersAfterUpdate(
  old: SettingsUsersResponse | undefined,
  id: string,
  input: UpdateUserInput,
): SettingsUsersResponse {
  return {
    users: (old?.users ?? []).map((u) =>
      u.id === id
        ? {
            ...u,
            role: input.role ?? u.role,
            groups: input.groups ?? u.groups,
            is_active: input.is_active ?? u.is_active,
          }
        : u,
    ),
  };
}

export function patchUsersAfterDelete(
  old: SettingsUsersResponse | undefined,
  id: string,
): SettingsUsersResponse {
  return { users: (old?.users ?? []).filter((u) => u.id !== id) };
}

export function createCreateGroupMutation() {
  const client = useQueryClient();
  return createMutation<
    SettingsGroup,
    Error,
    CreateGroupInput,
    { previous: SettingsGroupsResponse | undefined }
  >({
    mutationFn: (input) => createSettingsGroup(input),
    onMutate: async (input) => {
      await client.cancelQueries({ queryKey: qk.settingsGroups() });
      const previous = client.getQueryData<SettingsGroupsResponse>(qk.settingsGroups());
      client.setQueryData<SettingsGroupsResponse>(qk.settingsGroups(), (old) =>
        patchGroupsAfterCreate(old, input),
      );
      return { previous };
    },
    onError: (err, _vars, ctx) => {
      if (ctx?.previous) client.setQueryData(qk.settingsGroups(), ctx.previous);
      toast.error('Could not create group', { description: err.message });
    },
    onSuccess: () => {
      toast.success('Group created');
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: qk.settingsAll() });
    },
  });
}

export function createDeleteGroupMutation() {
  const client = useQueryClient();
  return createMutation<void, Error, string, { previous: SettingsGroupsResponse | undefined }>({
    mutationFn: (name) => deleteSettingsGroup(name),
    onMutate: async (name) => {
      await client.cancelQueries({ queryKey: qk.settingsGroups() });
      const previous = client.getQueryData<SettingsGroupsResponse>(qk.settingsGroups());
      client.setQueryData<SettingsGroupsResponse>(qk.settingsGroups(), (old) =>
        patchGroupsAfterDelete(old, name),
      );
      return { previous };
    },
    onError: (err, _vars, ctx) => {
      if (ctx?.previous) client.setQueryData(qk.settingsGroups(), ctx.previous);
      toast.error('Could not delete group', { description: err.message });
    },
    onSuccess: () => {
      toast.success('Group deleted');
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: qk.settingsAll() });
    },
  });
}

export function createCreateUserMutation() {
  const client = useQueryClient();
  return createMutation<
    SettingsUser,
    Error,
    CreateUserInput,
    { previous: SettingsUsersResponse | undefined }
  >({
    mutationFn: (input) => createSettingsUser(input),
    onMutate: async (input) => {
      await client.cancelQueries({ queryKey: qk.settingsUsers() });
      const previous = client.getQueryData<SettingsUsersResponse>(qk.settingsUsers());
      client.setQueryData<SettingsUsersResponse>(qk.settingsUsers(), (old) =>
        patchUsersAfterCreate(old, input),
      );
      return { previous };
    },
    onError: (err, _vars, ctx) => {
      if (ctx?.previous) client.setQueryData(qk.settingsUsers(), ctx.previous);
      toast.error('Could not invite user', { description: err.message });
    },
    onSuccess: () => {
      toast.success('User invited');
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: qk.settingsAll() });
    },
  });
}

export function createUpdateUserMutation() {
  const client = useQueryClient();
  return createMutation<
    SettingsUser,
    Error,
    { id: string; input: UpdateUserInput },
    { previous: SettingsUsersResponse | undefined }
  >({
    mutationFn: ({ id, input }) => updateSettingsUser(id, input),
    onMutate: async ({ id, input }) => {
      await client.cancelQueries({ queryKey: qk.settingsUsers() });
      const previous = client.getQueryData<SettingsUsersResponse>(qk.settingsUsers());
      client.setQueryData<SettingsUsersResponse>(qk.settingsUsers(), (old) =>
        patchUsersAfterUpdate(old, id, input),
      );
      return { previous };
    },
    onError: (err, _vars, ctx) => {
      if (ctx?.previous) client.setQueryData(qk.settingsUsers(), ctx.previous);
      toast.error('Could not update user', { description: err.message });
    },
    onSuccess: () => {
      toast.success('User updated');
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: qk.settingsAll() });
    },
  });
}

export function createDeleteUserMutation() {
  const client = useQueryClient();
  return createMutation<void, Error, string, { previous: SettingsUsersResponse | undefined }>({
    mutationFn: (id) => deleteSettingsUser(id),
    onMutate: async (id) => {
      await client.cancelQueries({ queryKey: qk.settingsUsers() });
      const previous = client.getQueryData<SettingsUsersResponse>(qk.settingsUsers());
      client.setQueryData<SettingsUsersResponse>(qk.settingsUsers(), (old) =>
        patchUsersAfterDelete(old, id),
      );
      return { previous };
    },
    onError: (err, _vars, ctx) => {
      if (ctx?.previous) client.setQueryData(qk.settingsUsers(), ctx.previous);
      toast.error('Could not delete user', { description: err.message });
    },
    onSuccess: () => {
      toast.success('User deleted');
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: qk.settingsAll() });
    },
  });
}

// ---- /v1/dash/settings/users/:id/permissions ---------------------------- //
//
// Row-level per-action grants (see server/src/rp_server/permissions.py).
// The grant mutation accepts the current admin's email so the UI can
// already render "granted by you" before the server roundtrip completes.

const _nowIso = (): string => new Date().toISOString();

export function patchPermissionsAfterGrant(
  old: UserPermissionsResponse | undefined,
  userId: string,
  input: GrantPermissionInput,
  actorEmail: string,
): UserPermissionsResponse {
  const placeholder: UserPermission = {
    id: `optimistic-${input.action}-${input.scope}-${Date.now()}`,
    user_id: userId,
    action: input.action,
    scope: input.scope,
    granted_by: actorEmail,
    granted_at: _nowIso(),
  };
  return {
    permissions: [placeholder, ...(old?.permissions ?? [])],
    allowed_actions: old?.allowed_actions ?? [],
  };
}

export function patchPermissionsAfterRevoke(
  old: UserPermissionsResponse | undefined,
  permissionId: string,
): UserPermissionsResponse {
  return {
    permissions: (old?.permissions ?? []).filter((p) => p.id !== permissionId),
    allowed_actions: old?.allowed_actions ?? [],
  };
}

export function createUserPermissionsQuery(userId: Readable<string>) {
  return createQuery<UserPermissionsResponse>(
    derived(userId, (id) => ({
      queryKey: qk.settingsUserPermissions(id),
      queryFn: ({ signal }: { signal: AbortSignal }) => listUserPermissions(id, undefined, signal),
      enabled: id.length > 0,
      staleTime: 10_000,
    })),
  );
}

export function createGrantPermissionMutation(actorEmail: string) {
  const client = useQueryClient();
  return createMutation<
    UserPermission,
    Error,
    { userId: string; input: GrantPermissionInput },
    { previous: UserPermissionsResponse | undefined; userId: string }
  >({
    mutationFn: ({ userId, input }) => grantUserPermission(userId, input),
    onMutate: async ({ userId, input }) => {
      const key = qk.settingsUserPermissions(userId);
      await client.cancelQueries({ queryKey: key });
      const previous = client.getQueryData<UserPermissionsResponse>(key);
      client.setQueryData<UserPermissionsResponse>(key, (old) =>
        patchPermissionsAfterGrant(old, userId, input, actorEmail),
      );
      return { previous, userId };
    },
    onError: (err, _vars, ctx) => {
      if (ctx) {
        client.setQueryData(qk.settingsUserPermissions(ctx.userId), ctx.previous);
      }
      toast.error('Could not grant permission', { description: err.message });
    },
    onSuccess: () => {
      toast.success('Permission granted');
    },
    onSettled: (_data, _err, vars) => {
      void client.invalidateQueries({
        queryKey: qk.settingsUserPermissions(vars.userId),
      });
    },
  });
}

export function createRevokePermissionMutation() {
  const client = useQueryClient();
  return createMutation<
    void,
    Error,
    { userId: string; permissionId: string },
    { previous: UserPermissionsResponse | undefined; userId: string }
  >({
    mutationFn: ({ userId, permissionId }) => revokeUserPermission(userId, permissionId),
    onMutate: async ({ userId, permissionId }) => {
      const key = qk.settingsUserPermissions(userId);
      await client.cancelQueries({ queryKey: key });
      const previous = client.getQueryData<UserPermissionsResponse>(key);
      client.setQueryData<UserPermissionsResponse>(key, (old) =>
        patchPermissionsAfterRevoke(old, permissionId),
      );
      return { previous, userId };
    },
    onError: (err, _vars, ctx) => {
      if (ctx) {
        client.setQueryData(qk.settingsUserPermissions(ctx.userId), ctx.previous);
      }
      toast.error('Could not revoke permission', { description: err.message });
    },
    onSuccess: () => {
      toast.success('Permission revoked');
    },
    onSettled: (_data, _err, vars) => {
      void client.invalidateQueries({
        queryKey: qk.settingsUserPermissions(vars.userId),
      });
    },
  });
}

// ---- /v1/dash/enroll/* (magic-link issuance from the dashboard) ----

export function createEnrollLinksQuery() {
  return createQuery<EnrollLinkListResponse>({
    queryKey: qk.enrollLinks(),
    queryFn: ({ signal }) => getEnrollLinks(undefined, signal),
    staleTime: 30_000,
  });
}

export function createCreateEnrollLinkMutation() {
  const client = useQueryClient();
  return createMutation<EnrollLinkOut, Error, EnrollLinkCreateInput>({
    mutationFn: (input: EnrollLinkCreateInput) => createEnrollLink(input),
    onSuccess: () => {
      toast.success('Magic-link generated');
      void client.invalidateQueries({ queryKey: qk.enrollAll() });
    },
    onError: (err: Error) => {
      toast.error('Could not generate magic-link', { description: err.message });
    },
  });
}

export function createRevokeEnrollLinkMutation() {
  const client = useQueryClient();
  return createMutation({
    mutationFn: (token_jti: string) => revokeEnrollLink(token_jti),
    onSuccess: () => {
      toast.success('Magic-link revoked');
      void client.invalidateQueries({ queryKey: qk.enrollAll() });
    },
    onError: (err: Error) => {
      toast.error('Could not revoke magic-link', { description: err.message });
    },
  });
}

// ---- /v1/dash/hosts/:id (DELETE) ---------------------------------------- //
//
// Optimistic remove from any cached fleet listing while the DELETE flies.
// The `hostsAll()` family key sweeps every parameter combination that has
// been seeded into the cache, so users on Hosts/Fleet with different
// filters all see the row vanish in lock-step.

export function patchHostsAfterDelete(old: HostsList | undefined, hostId: string): HostsList {
  return {
    hosts: (old?.hosts ?? []).filter((h) => h.id !== hostId),
    groups: old?.groups ?? [],
  };
}

interface DeleteHostContext {
  snapshots: Array<[readonly unknown[], HostsList | undefined]>;
}

export function createDeleteHostMutation() {
  const client = useQueryClient();
  return createMutation<void, Error, string, DeleteHostContext>({
    mutationFn: (id) => deleteHost(id),
    onMutate: async (id) => {
      // Cancel any in-flight refetches so they don't stomp the optimistic
      // patch before the DELETE resolves.
      await client.cancelQueries({ queryKey: qk.hostsAll() });
      await client.cancelQueries({ queryKey: qk.host(id) });

      // Snapshot every cached hosts list (HostsParams varies per page) so
      // we can roll back the whole family on failure.
      const snapshots = client
        .getQueriesData<HostsList>({ queryKey: qk.hostsAll() })
        .map(([key, data]) => [key, data] as [readonly unknown[], HostsList | undefined]);

      for (const [key] of snapshots) {
        client.setQueryData<HostsList>(key, (old) => patchHostsAfterDelete(old, id));
      }
      // The single-host cache becomes meaningless once the row is gone.
      client.removeQueries({ queryKey: qk.host(id) });

      return { snapshots };
    },
    onError: (err, _id, ctx) => {
      if (ctx) {
        for (const [key, data] of ctx.snapshots) {
          client.setQueryData(key, data);
        }
      }
      toast.error('Could not delete host', { description: err.message });
    },
    onSuccess: () => {
      toast.success('Host deleted');
    },
    onSettled: (_data, _err, id) => {
      // Re-fetch fleet, hosts list, overview (host counts), audit (delete
      // event), and the now-defunct single-host detail (so consumers get
      // a 404 instead of stale data).
      void client.invalidateQueries({ queryKey: qk.hostsAll() });
      void client.invalidateQueries({ queryKey: qk.overview() });
      void client.invalidateQueries({ queryKey: qk.auditAll() });
      void client.invalidateQueries({ queryKey: qk.host(id) });
    },
  });
}

// ---- /v1/dash/webhooks/* ----------------------------------------------- //
//
// Single list query (no per-row cache); mutations invalidate the whole
// `['webhooks']` key. Volumes are tiny (handful of hooks per tenant) so
// the patch helpers are deliberately straightforward — no optimistic
// updates beyond what the toast feedback already conveys.

export function createWebhooksQuery() {
  return createQuery<WebhookListResponse>({
    queryKey: qk.webhooks(),
    queryFn: ({ signal }) => getWebhooks(undefined, signal),
    staleTime: 30_000,
  });
}

export function createCreateWebhookMutation() {
  const client = useQueryClient();
  return createMutation<WebhookCreateResponse, Error, CreateWebhookInput>({
    mutationFn: (input) => createWebhook(input),
    onSuccess: () => {
      toast.success('Webhook created');
    },
    onError: (err) => {
      toast.error('Could not create webhook', { description: err.message });
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: qk.webhooks() });
    },
  });
}

export function createUpdateWebhookMutation() {
  const client = useQueryClient();
  return createMutation<
    WebhookSummary,
    Error,
    { id: string; input: UpdateWebhookInput }
  >({
    mutationFn: ({ id, input }) => updateWebhook(id, input),
    onSuccess: () => {
      toast.success('Webhook updated');
    },
    onError: (err) => {
      toast.error('Could not update webhook', { description: err.message });
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: qk.webhooks() });
    },
  });
}

export function createDeleteWebhookMutation() {
  const client = useQueryClient();
  return createMutation<void, Error, string>({
    mutationFn: (id) => deleteWebhook(id),
    onSuccess: () => {
      toast.success('Webhook deleted');
    },
    onError: (err) => {
      toast.error('Could not delete webhook', { description: err.message });
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: qk.webhooks() });
    },
  });
}

export function createTestWebhookMutation() {
  const client = useQueryClient();
  return createMutation<void, Error, string>({
    mutationFn: (id) => testWebhook(id),
    onSuccess: () => {
      toast.success('Test event queued — check Deliveries for the result');
    },
    onError: (err) => {
      toast.error('Could not test webhook', { description: err.message });
    },
    onSettled: () => {
      // The dispatcher writes the delivery outcome back asynchronously;
      // invalidate so the next refetch picks up `last_status_code` etc.
      void client.invalidateQueries({ queryKey: qk.webhooks() });
    },
  });
}

// ---- ergonomic helper: wrap a value-returning accessor into a Readable ----
// The caller MUST call this within a Svelte component (so the underlying
// reactive read happens in the component's render scope). The accessor is
// invoked once on subscribe; updates flow via a writable backed by a
// `$effect` inside the consuming component (see queries/reactive.svelte.ts).
export function staticReadable<T>(value: T): Readable<T> {
  return readable(value);
}
