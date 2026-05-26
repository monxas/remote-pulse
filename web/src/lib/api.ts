/**
 * Typed fetch wrapper for the Remote-Pulse server. Cookie-based session auth
 * (rp_session). All endpoints share an origin in production; in dev the Vite
 * proxy forwards /v1 + /auth to localhost:8080. ADR-0009 §3.3.
 */

export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, message: string, body?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }
}

type FetchFn = typeof fetch;

interface ApiOptions {
  fetch?: FetchFn;
  signal?: AbortSignal;
}

async function request<T>(path: string, init: RequestInit, opts: ApiOptions = {}): Promise<T> {
  const f: FetchFn = opts.fetch ?? fetch;
  const res = await f(path, {
    credentials: 'same-origin',
    headers: {
      Accept: 'application/json',
      ...(init.headers ?? {}),
    },
    signal: opts.signal,
    ...init,
  });

  const ctype = res.headers.get('content-type') ?? '';
  const isJson = ctype.includes('application/json');
  const body: unknown = isJson ? await res.json().catch(() => null) : await res.text();

  if (!res.ok) {
    const msg =
      isJson && body && typeof body === 'object' && 'detail' in body
        ? String((body as { detail: unknown }).detail)
        : `HTTP ${res.status}`;
    throw new ApiError(res.status, msg, body);
  }
  return body as T;
}

// ---------- /auth/me ----------
export interface AuthMe {
  user_id: string | null;
  user_email: string | null;
  user_role: string | null;
  authenticated: boolean;
}

export async function getAuthMe(f?: FetchFn): Promise<AuthMe> {
  return request<AuthMe>('/auth/me', { method: 'GET' }, { fetch: f });
}

// ---------- /v1/dash/overview ----------
export interface DashOverview {
  total: number;
  online: number;
  stale: number;
  offline: number;
  pending_approvals: number;
  online_pct: number;
  online_pct_24h_ago: number;
}

export async function getDashOverview(f?: FetchFn, signal?: AbortSignal): Promise<DashOverview> {
  return request<DashOverview>('/v1/dash/overview', { method: 'GET' }, { fetch: f, signal });
}

// ---------- /v1/dash/hosts ----------
export type HostStatus = 'online' | 'stale' | 'offline' | 'unknown';

export interface HostCurrent {
  cpu_pct: number | null;
  mem_pct: number | null;
  load_1m: number | null;
  uptime_s: number | null;
}

export interface HostSparkline {
  window_s: number;
  bucket_s: number;
  ts: number[];
  cpu_pct: (number | null)[];
  mem_pct: (number | null)[];
}

export interface HostSummary {
  id: string;
  hostname: string;
  group_name: string;
  status: HostStatus;
  last_seen_at: string | null;
  last_seen_seconds_ago: number | null;
  os_family: string | null;
  agent_version: string | null;
  tailscale_ip: string | null;
  current: HostCurrent;
  sparkline: HostSparkline;
}

export interface HostsList {
  hosts: HostSummary[];
  groups: string[];
}

export interface HostsQueryParams {
  group?: string;
  status?: HostStatus;
  q?: string;
  window?: string;
}

export async function getDashHosts(
  params: HostsQueryParams = {},
  f?: FetchFn,
  signal?: AbortSignal,
): Promise<HostsList> {
  const usp = new URLSearchParams();
  if (params.group) usp.set('group', params.group);
  if (params.status) usp.set('status', params.status);
  if (params.q) usp.set('q', params.q);
  if (params.window) usp.set('window', params.window);
  const qs = usp.toString();
  return request<HostsList>(
    `/v1/dash/hosts${qs ? `?${qs}` : ''}`,
    { method: 'GET' },
    { fetch: f, signal },
  );
}

// ---------- /v1/dash/hosts/:id/timeseries ----------
export interface TimeseriesPayload {
  host_id: string;
  window_s: number;
  bucket_s: number;
  ts: number[];
  cpu_pct?: (number | null)[];
  mem_pct?: (number | null)[];
  load_1m?: (number | null)[];
  net_rx_kbps?: (number | null)[];
  net_tx_kbps?: (number | null)[];
}

export interface TimeseriesQueryParams {
  window: string;
  series: string[];
}

export async function getDashTimeseries(
  hostId: string,
  params: TimeseriesQueryParams,
  f?: FetchFn,
  signal?: AbortSignal,
): Promise<TimeseriesPayload> {
  const usp = new URLSearchParams();
  usp.set('window', params.window);
  if (params.series.length > 0) usp.set('series', params.series.join(','));
  return request<TimeseriesPayload>(
    `/v1/dash/hosts/${encodeURIComponent(hostId)}/timeseries?${usp.toString()}`,
    { method: 'GET' },
    { fetch: f, signal },
  );
}

// ---------- /v1/dash/commands ----------
export type CommandStatus =
  | 'pending-approval'
  | 'approved'
  | 'queued'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'timeout'
  | 'rejected'
  | 'canceled';

export const ALL_COMMAND_STATUSES: ReadonlyArray<CommandStatus> = [
  'pending-approval',
  'approved',
  'queued',
  'running',
  'succeeded',
  'failed',
  'timeout',
  'rejected',
  'canceled',
];

export const IN_FLIGHT_STATUSES: ReadonlySet<CommandStatus> = new Set<CommandStatus>([
  'pending-approval',
  'approved',
  'queued',
  'running',
]);

export interface CommandRecord {
  id: string;
  host_id: string;
  host_hostname: string;
  issued_by: string;
  command_type: string;
  command_payload: Record<string, unknown>;
  status: CommandStatus;
  issued_at: string;
  completed_at: string | null;
  exit_code: number | null;
  stdout: string | null;
  stderr: string | null;
  duration_ms: number | null;
  human_approved: boolean;
  approved_by: string | null;
  rejected_reason: string | null;
}

export interface CommandsListPage {
  commands: CommandRecord[];
  next_cursor: string | null;
}

export interface CommandsQueryParams {
  status?: CommandStatus[];
  host_id?: string;
  issued_by?: string;
  limit?: number;
  cursor?: string;
}

function buildCommandsQuery(params: CommandsQueryParams): string {
  const usp = new URLSearchParams();
  if (params.status && params.status.length > 0) {
    // Server contract: repeat the `status` key once per value.
    for (const s of params.status) usp.append('status', s);
  }
  if (params.host_id) usp.set('host_id', params.host_id);
  if (params.issued_by) usp.set('issued_by', params.issued_by);
  if (typeof params.limit === 'number') usp.set('limit', String(params.limit));
  if (params.cursor) usp.set('cursor', params.cursor);
  const qs = usp.toString();
  return qs ? `?${qs}` : '';
}

export async function getDashCommands(
  params: CommandsQueryParams = {},
  f?: FetchFn,
  signal?: AbortSignal,
): Promise<CommandsListPage> {
  return request<CommandsListPage>(
    `/v1/dash/commands${buildCommandsQuery(params)}`,
    { method: 'GET' },
    { fetch: f, signal },
  );
}

export async function getDashCommand(
  id: string,
  f?: FetchFn,
  signal?: AbortSignal,
): Promise<CommandRecord> {
  return request<CommandRecord>(
    `/v1/dash/commands/${encodeURIComponent(id)}`,
    { method: 'GET' },
    { fetch: f, signal },
  );
}

export interface IssueCommandInput {
  host_ids: string[];
  command_type: string;
  command_payload: Record<string, unknown>;
  reason?: string;
  requires_approval?: boolean;
}

export interface IssueCommandResult {
  commands: CommandRecord[];
}

export async function issueDashCommand(
  body: IssueCommandInput,
  f?: FetchFn,
  signal?: AbortSignal,
): Promise<IssueCommandResult> {
  return request<IssueCommandResult>(
    '/v1/dash/commands',
    {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    },
    { fetch: f, signal },
  );
}

export async function retryDashCommand(
  id: string,
  f?: FetchFn,
  signal?: AbortSignal,
): Promise<CommandRecord> {
  return request<CommandRecord>(
    `/v1/dash/commands/${encodeURIComponent(id)}/retry`,
    { method: 'POST' },
    { fetch: f, signal },
  );
}

// ---------- /v1/dash/approvals ----------
export interface PendingApprovalsResponse {
  approvals: CommandRecord[];
}

export async function getDashPendingApprovals(
  f?: FetchFn,
  signal?: AbortSignal,
): Promise<PendingApprovalsResponse> {
  return request<PendingApprovalsResponse>(
    '/v1/dash/approvals/pending',
    { method: 'GET' },
    { fetch: f, signal },
  );
}

export interface ApprovalActionResponse {
  ok: true;
  command: CommandRecord;
}

export async function approveDashCommand(
  id: string,
  f?: FetchFn,
  signal?: AbortSignal,
): Promise<ApprovalActionResponse> {
  return request<ApprovalActionResponse>(
    `/v1/dash/approvals/${encodeURIComponent(id)}/approve`,
    { method: 'POST' },
    { fetch: f, signal },
  );
}

export async function rejectDashCommand(
  id: string,
  reason: string,
  f?: FetchFn,
  signal?: AbortSignal,
): Promise<ApprovalActionResponse> {
  return request<ApprovalActionResponse>(
    `/v1/dash/approvals/${encodeURIComponent(id)}/reject`,
    {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ reason }),
    },
    { fetch: f, signal },
  );
}

// ---------- /v1/dash/audit ----------
export type AuditAction =
  | 'command.issued'
  | 'command.approved'
  | 'command.rejected'
  | 'command.completed'
  | 'command.failed'
  | 'host.enrolled'
  | 'enrollment.token_issued'
  | 'settings.group.create'
  | 'settings.group.delete'
  | 'settings.user.create'
  | 'settings.user.update'
  | 'settings.user.delete'
  | 'settings.permission.grant'
  | 'settings.permission.revoke';

export const ALL_AUDIT_ACTIONS: ReadonlyArray<AuditAction> = [
  'command.issued',
  'command.approved',
  'command.rejected',
  'command.completed',
  'command.failed',
  'host.enrolled',
  'enrollment.token_issued',
  'settings.group.create',
  'settings.group.delete',
  'settings.user.create',
  'settings.user.update',
  'settings.user.delete',
  'settings.permission.grant',
  'settings.permission.revoke',
];

export type AuditTargetType = 'command' | 'host' | 'enrollment' | 'user' | 'group';

export interface AuditEvent {
  id: string;
  ts: string;
  actor: string;
  action: AuditAction;
  target_type: AuditTargetType;
  target_id: string;
  target_label: string;
  metadata: Record<string, unknown>;
}

export interface AuditListPage {
  events: AuditEvent[];
  next_cursor: string | null;
}

export interface AuditQueryParams {
  actor?: string;
  action?: AuditAction[];
  target_type?: AuditTargetType;
  since?: string;
  until?: string;
  limit?: number;
  cursor?: string;
}

function buildAuditQuery(params: AuditQueryParams): string {
  const usp = new URLSearchParams();
  if (params.actor) usp.set('actor', params.actor);
  if (params.action && params.action.length > 0) {
    for (const a of params.action) usp.append('action', a);
  }
  if (params.target_type) usp.set('target_type', params.target_type);
  if (params.since) usp.set('since', params.since);
  if (params.until) usp.set('until', params.until);
  if (typeof params.limit === 'number') usp.set('limit', String(params.limit));
  if (params.cursor) usp.set('cursor', params.cursor);
  const qs = usp.toString();
  return qs ? `?${qs}` : '';
}

export async function getDashAudit(
  params: AuditQueryParams = {},
  f?: FetchFn,
  signal?: AbortSignal,
): Promise<AuditListPage> {
  return request<AuditListPage>(
    `/v1/dash/audit${buildAuditQuery(params)}`,
    { method: 'GET' },
    { fetch: f, signal },
  );
}

// ---------- /v1/dash/settings/* (ADR-0009 Phase 4) ----------
export interface SettingsGroup {
  name: string;
  description: string | null;
  host_count: number;
  user_count: number;
  auto_distribute_keys: boolean;
  created_at: string;
}

export interface SettingsGroupsResponse {
  groups: SettingsGroup[];
}

export type UserRole = 'admin' | 'operator' | 'viewer';

export interface SettingsUser {
  id: string;
  email: string;
  name: string | null;
  role: UserRole;
  groups: string[];
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface SettingsUsersResponse {
  users: SettingsUser[];
}

export interface CreateGroupInput {
  name: string;
  description?: string | null;
}

export interface CreateUserInput {
  email: string;
  name?: string | null;
  role: UserRole;
  groups: string[];
}

export interface UpdateUserInput {
  role?: UserRole;
  groups?: string[];
  is_active?: boolean;
}

export async function getSettingsGroups(
  f?: FetchFn,
  signal?: AbortSignal,
): Promise<SettingsGroupsResponse> {
  return request<SettingsGroupsResponse>(
    '/v1/dash/settings/groups',
    { method: 'GET' },
    { fetch: f, signal },
  );
}

export async function createSettingsGroup(
  input: CreateGroupInput,
  f?: FetchFn,
): Promise<SettingsGroup> {
  return request<SettingsGroup>(
    '/v1/dash/settings/groups',
    {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(input),
    },
    { fetch: f },
  );
}

export async function deleteSettingsGroup(name: string, f?: FetchFn): Promise<void> {
  await request<unknown>(
    `/v1/dash/settings/groups/${encodeURIComponent(name)}`,
    { method: 'DELETE' },
    { fetch: f },
  );
}

export async function getSettingsUsers(
  f?: FetchFn,
  signal?: AbortSignal,
): Promise<SettingsUsersResponse> {
  return request<SettingsUsersResponse>(
    '/v1/dash/settings/users',
    { method: 'GET' },
    { fetch: f, signal },
  );
}

export async function createSettingsUser(
  input: CreateUserInput,
  f?: FetchFn,
): Promise<SettingsUser> {
  return request<SettingsUser>(
    '/v1/dash/settings/users',
    {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(input),
    },
    { fetch: f },
  );
}

export async function updateSettingsUser(
  id: string,
  input: UpdateUserInput,
  f?: FetchFn,
): Promise<SettingsUser> {
  return request<SettingsUser>(
    `/v1/dash/settings/users/${encodeURIComponent(id)}`,
    {
      method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(input),
    },
    { fetch: f },
  );
}

export async function deleteSettingsUser(id: string, f?: FetchFn): Promise<void> {
  await request<unknown>(
    `/v1/dash/settings/users/${encodeURIComponent(id)}`,
    { method: 'DELETE' },
    { fetch: f },
  );
}

// ---------- /v1/dash/settings/users/:id/permissions ----------
//
// Row-level per-action grants that layer on top of role + accessible_groups.
// Admins implicitly hold every action and don't need rows; for non-admins
// the server enforces these via rp_server.permissions.user_has_permission.

/** Canonical action enum. Kept in sync with rp_server.permissions.ALLOWED_ACTIONS. */
export type PermissionAction =
  | 'command.issue'
  | 'command.approve'
  | 'host.delete'
  | 'enroll.create';

export const ALL_PERMISSION_ACTIONS: ReadonlyArray<PermissionAction> = [
  'command.issue',
  'command.approve',
  'host.delete',
  'enroll.create',
];

export interface UserPermission {
  id: string;
  user_id: string;
  action: string;
  scope: string;
  granted_by: string;
  granted_at: string;
}

export interface UserPermissionsResponse {
  permissions: UserPermission[];
  /** Server-supplied enum so the UI doesn't ship its own copy. */
  allowed_actions: string[];
}

export interface GrantPermissionInput {
  action: PermissionAction;
  /** Group name pattern. ``*`` grants every scope. */
  scope: string;
}

export async function listUserPermissions(
  userId: string,
  f?: FetchFn,
  signal?: AbortSignal,
): Promise<UserPermissionsResponse> {
  return request<UserPermissionsResponse>(
    `/v1/dash/settings/users/${encodeURIComponent(userId)}/permissions`,
    { method: 'GET' },
    { fetch: f, signal },
  );
}

export async function grantUserPermission(
  userId: string,
  input: GrantPermissionInput,
  f?: FetchFn,
): Promise<UserPermission> {
  return request<UserPermission>(
    `/v1/dash/settings/users/${encodeURIComponent(userId)}/permissions`,
    {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(input),
    },
    { fetch: f },
  );
}

export async function revokeUserPermission(
  userId: string,
  permissionId: string,
  f?: FetchFn,
): Promise<void> {
  await request<unknown>(
    `/v1/dash/settings/users/${encodeURIComponent(userId)}/permissions/${encodeURIComponent(permissionId)}`,
    { method: 'DELETE' },
    { fetch: f },
  );
}

// ---------- /v1/dash/enroll/* (magic-link issuance from the dashboard) ----------
//
// Mirrors `server/src/rp_server/routers/dash_enroll.py`. Admin-only on the
// server side; the UI does not gate the calls itself — it lets the server
// answer 403 and renders the error inline.

export interface EnrollLinkCreateInput {
  group_name: string;
  ttl_hours: number;
  max_uses: number;
  label?: string | null;
}

export interface EnrollLinkOut {
  url: string;
  install_url_windows: string;
  token: string;
  token_jti: string;
  group_name: string;
  issued_by: string;
  expires_at: string;
  expires_in_hours: number;
  max_uses: number;
  used_count: number;
  label: string | null;
}

export interface EnrollLinkSummary {
  token_jti: string;
  group_name: string;
  issued_by: string;
  expires_at: string;
  max_uses: number;
  used_count: number;
  created_at: string;
}

export interface EnrollLinkListResponse {
  links: EnrollLinkSummary[];
}

export async function getEnrollLinks(
  f?: FetchFn,
  signal?: AbortSignal,
): Promise<EnrollLinkListResponse> {
  return request<EnrollLinkListResponse>(
    '/v1/dash/enroll/links',
    { method: 'GET' },
    { fetch: f, signal },
  );
}

export async function createEnrollLink(
  input: EnrollLinkCreateInput,
  f?: FetchFn,
): Promise<EnrollLinkOut> {
  return request<EnrollLinkOut>(
    '/v1/dash/enroll/links',
    {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(input),
    },
    { fetch: f },
  );
}

export async function revokeEnrollLink(token_jti: string, f?: FetchFn): Promise<void> {
  await request<unknown>(
    `/v1/dash/enroll/links/${encodeURIComponent(token_jti)}`,
    { method: 'DELETE' },
    { fetch: f },
  );
}

// Exported for unit tests — keeps URL serialisation honest with the
// backend contract (multi-value status / action, cursor-paged).
export const __testing = {
  buildCommandsQuery,
  buildAuditQuery,
};
