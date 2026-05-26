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
  createSettingsGroup,
  createSettingsUser,
  deleteSettingsGroup,
  deleteSettingsUser,
  getDashAudit,
  getDashCommand,
  getDashCommands,
  getDashHosts,
  getDashOverview,
  getDashPendingApprovals,
  getDashTimeseries,
  getSettingsGroups,
  getSettingsUsers,
  IN_FLIGHT_STATUSES,
  issueDashCommand,
  rejectDashCommand,
  retryDashCommand,
  updateSettingsUser,
  type AuditListPage,
  type AuditQueryParams,
  type CommandRecord,
  type CommandsListPage,
  type CommandsQueryParams,
  type CreateGroupInput,
  type CreateUserInput,
  type DashOverview,
  type HostStatus,
  type HostsList,
  type HostSummary,
  type IssueCommandInput,
  type PendingApprovalsResponse,
  type SettingsGroupsResponse,
  type SettingsUsersResponse,
  type TimeseriesPayload,
  type UpdateUserInput,
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
  settingsAll: () => ['settings'] as const,
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

export function createCreateGroupMutation() {
  const client = useQueryClient();
  return createMutation({
    mutationFn: (input: CreateGroupInput) => createSettingsGroup(input),
    onSuccess: () => {
      toast.success('Group created');
      void client.invalidateQueries({ queryKey: qk.settingsAll() });
    },
    onError: (err: Error) => {
      toast.error('Could not create group', { description: err.message });
    },
  });
}

export function createDeleteGroupMutation() {
  const client = useQueryClient();
  return createMutation({
    mutationFn: (name: string) => deleteSettingsGroup(name),
    onSuccess: () => {
      toast.success('Group deleted');
      void client.invalidateQueries({ queryKey: qk.settingsAll() });
    },
    onError: (err: Error) => {
      toast.error('Could not delete group', { description: err.message });
    },
  });
}

export function createCreateUserMutation() {
  const client = useQueryClient();
  return createMutation({
    mutationFn: (input: CreateUserInput) => createSettingsUser(input),
    onSuccess: () => {
      toast.success('User invited');
      void client.invalidateQueries({ queryKey: qk.settingsAll() });
    },
    onError: (err: Error) => {
      toast.error('Could not invite user', { description: err.message });
    },
  });
}

export function createUpdateUserMutation() {
  const client = useQueryClient();
  return createMutation({
    mutationFn: ({ id, input }: { id: string; input: UpdateUserInput }) =>
      updateSettingsUser(id, input),
    onSuccess: () => {
      toast.success('User updated');
      void client.invalidateQueries({ queryKey: qk.settingsAll() });
    },
    onError: (err: Error) => {
      toast.error('Could not update user', { description: err.message });
    },
  });
}

export function createDeleteUserMutation() {
  const client = useQueryClient();
  return createMutation({
    mutationFn: (id: string) => deleteSettingsUser(id),
    onSuccess: () => {
      toast.success('User deleted');
      void client.invalidateQueries({ queryKey: qk.settingsAll() });
    },
    onError: (err: Error) => {
      toast.error('Could not delete user', { description: err.message });
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
