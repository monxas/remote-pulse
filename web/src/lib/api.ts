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
  // 204 No Content has no body — callers must declare `Promise<void>`.
  const isNoContent = res.status === 204;
  const body: unknown = isNoContent
    ? null
    : isJson
      ? await res.json().catch(() => null)
      : await res.text();

  if (!res.ok) {
    const msg =
      isJson && body && typeof body === 'object' && 'detail' in body
        ? String((body as { detail: unknown }).detail)
        : `HTTP ${res.status}`;
    throw new ApiError(res.status, msg, body);
  }

  if (isNoContent) {
    return undefined as T;
  }

  // Guard against non-JSON 200s: some dev/preview proxies (e.g. `vite
  // preview`'s SPA fallback) return the index.html for unknown `/v1/*`
  // paths with a 200 status. Without this check the caller would get a
  // raw string typed as `T`, triggering downstream `.toFixed`/`.length`
  // errors and dragging the Lighthouse best-practices score down.
  if (!isJson) {
    throw new ApiError(res.status, `Expected JSON, got ${ctype || 'unknown'}`, body);
  }
  return body as T;
}

// ---------- /auth/me ----------
export interface AuthMePermission {
  action: string;
  scope: string;
}

export interface AuthMe {
  user_id: string | null;
  user_email: string | null;
  user_role: string | null;
  authenticated: boolean;
  /**
   * Row-level grants for the authenticated user. Always present (possibly
   * empty). Admins implicitly bypass — their permissions list is empty
   * and `userStore.hasPermission()` short-circuits on `role === 'admin'`.
   * Field added in v1.0.14 for client-side capability gating.
   */
  permissions?: AuthMePermission[];
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

// ---------- /v1/dash/hosts/:id (DELETE) ----------
//
// Permanently deletes a host and cascades its dependent rows (heartbeats,
// metrics, commands, ssh_keys, agent_versions). Server returns 204 No
// Content on success; the wrapper resolves with `undefined`. Errors:
//  - 403 if caller lacks `host.delete` for the host's group
//  - 404 if host id is unknown / outside caller's accessible_groups
//  - 409 if host is the canary of an in-flight deploy
export async function deleteHost(hostId: string, f?: FetchFn): Promise<void> {
  await request<unknown>(
    `/v1/dash/hosts/${encodeURIComponent(hostId)}`,
    { method: 'DELETE' },
    { fetch: f },
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
  /**
   * Total events matching the filters, independent of pagination. The
   * fields below are populated on every response from the v1.0.11+
   * backend but are kept optional so older fixtures + mocks remain
   * type-compatible.
   */
  total?: number;
  limit?: number;
  offset?: number;
  has_more?: boolean;
}

export interface AuditQueryParams {
  actor?: string;
  action?: AuditAction[];
  action_prefix?: string;
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
  if (params.action_prefix) usp.set('action_prefix', params.action_prefix);
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

/**
 * Build the URL for the admin-only audit export endpoint with the current
 * filter params applied. ``format`` selects CSV (default) or JSON. Returned
 * as a relative URL so the caller can either ``fetch()`` it (to surface
 * 403s) or wire it up as an anchor ``href`` for native download.
 */
export function buildAuditExportUrl(
  params: AuditQueryParams = {},
  format: 'csv' | 'json' = 'csv',
): string {
  // Strip the cursor + limit — export ignores both. ``buildAuditQuery``
  // already handles repeatable ``action``.
  const { cursor: _cursor, limit: _limit, ...rest } = params;
  void _cursor;
  void _limit;
  const qs = buildAuditQuery(rest);
  const sep = qs ? '&' : '?';
  return `/v1/dash/audit/export${qs}${sep}format=${format}`;
}

// ---------- /v1/dash/stats ----------
export type StatsRange = '24h' | '7d' | '30d' | '90d';

export const ALL_STATS_RANGES: ReadonlyArray<StatsRange> = ['24h', '7d', '30d', '90d'] as const;

export interface StatsFleet {
  total_hosts: number;
  online_now: number;
  offline_now: number;
  uptime_percent: number;
}

export interface StatsCommandType {
  type: string;
  count: number;
}

export interface StatsCommandDaily {
  day: string;
  issued: number;
  succeeded: number;
  failed: number;
}

export interface StatsCommands {
  total: number;
  succeeded: number;
  failed: number;
  pending: number;
  success_rate: number;
  by_type: StatsCommandType[];
  daily: StatsCommandDaily[];
}

export interface StatsHeartbeats {
  total: number;
  per_host_avg_per_min: number;
  stale_events: number;
  offline_events: number;
}

export interface StatsHostUptime {
  hostname: string;
  uptime_percent: number;
  downtime_minutes: number;
}

export interface StatsAuditEntry {
  action: string;
  count: number;
}

export interface StatsAuditActor {
  actor: string;
  count: number;
}

export interface StatsAuditDaily {
  day: string;
  count: number;
}

export interface StatsAuditSummary {
  total_events: number;
  by_action: StatsAuditEntry[];
  by_actor: StatsAuditActor[];
  /** Per-day counts across the requested range. New in v1.0.15. */
  daily?: StatsAuditDaily[];
}

export interface DashStats {
  range: StatsRange;
  fleet: StatsFleet;
  commands: StatsCommands;
  heartbeats: StatsHeartbeats;
  uptime_per_host: StatsHostUptime[];
  audit_summary: StatsAuditSummary;
}

export async function getDashStats(
  range: StatsRange,
  f?: FetchFn,
  signal?: AbortSignal,
): Promise<DashStats> {
  return request<DashStats>(
    `/v1/dash/stats?range=${encodeURIComponent(range)}`,
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
  | 'enroll.create'
  | 'enroll.revoke';

export const ALL_PERMISSION_ACTIONS: ReadonlyArray<PermissionAction> = [
  'command.issue',
  'command.approve',
  'host.delete',
  'enroll.create',
  'enroll.revoke',
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
  // TTL: prefer `ttl_minutes` (default 5 min, max 1440). `ttl_hours` is
  // retained for backwards compatibility with the legacy 24h form and the
  // existing tests; the server's pydantic validator caps it at 24h now.
  ttl_minutes?: number;
  ttl_hours?: number;
  max_uses: number;
  label?: string | null;
}

export interface EnrollLinkOut {
  // ---- New short-code surface (preferred) ----
  code: string; // "XXX-XXX" display form
  install_url: string; // curl ... | sh -s -- --code=XXX-XXX
  install_url_windows_short: string;
  // ---- Legacy (deprecated, kept for back-compat) ----
  url: string;
  install_url_windows: string;
  token: string;
  // ---- Metadata ----
  token_jti: string;
  group_name: string;
  issued_by: string;
  expires_at: string;
  expires_in_seconds: number;
  expires_in_hours: number;
  max_uses: number;
  used_count: number;
  label: string | null;
}

export interface EnrollLinkSummary {
  token_jti: string;
  code: string | null;
  install_url_short: string | null;
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

// ---------- /v1/dash/webhooks/* (outbound webhook subscriptions) ----------
//
// Mirrors `server/src/rp_server/routers/dash_webhooks.py`. Admin-only on the
// server; the UI hides the nav entry for non-admins but the server is the
// source of truth (403 on any non-admin call).

export interface WebhookSummary {
  id: string;
  name: string;
  url: string;
  /** Match rules: ``*`` (all), ``prefix.`` (e.g. ``command.``), or ``exact.event``. */
  event_filter: string[];
  /** ``null`` means "match any group". */
  group_filter: string[] | null;
  enabled: boolean;
  created_by: string;
  created_at: string;
  last_fired_at: string | null;
  last_status_code: number | null;
  last_error: string | null;
  failure_count: number;
}

export interface WebhookListResponse {
  webhooks: WebhookSummary[];
}

/** Surfaced only in the immediate response to `POST /v1/dash/webhooks`. */
export interface WebhookCreateResponse extends WebhookSummary {
  secret: string;
}

export interface CreateWebhookInput {
  name: string;
  url: string;
  event_filter: string[];
  group_filter?: string[] | null;
}

export interface UpdateWebhookInput {
  name?: string;
  url?: string;
  event_filter?: string[];
  group_filter?: string[] | null;
  enabled?: boolean;
}

export interface WebhookDeliveryEntry {
  delivery_id: string;
  event: string;
  timestamp: string;
  status_code: number | null;
  error: string | null;
  attempt: number;
  success: boolean;
  /** Set on records produced by the manual retry endpoint — original delivery_id. */
  retry_of?: string | null;
}

export interface WebhookDeliveriesResponse {
  webhook_id: string;
  deliveries: WebhookDeliveryEntry[];
  max_history: number;
}

export async function getWebhooks(f?: FetchFn, signal?: AbortSignal): Promise<WebhookListResponse> {
  return request<WebhookListResponse>('/v1/dash/webhooks', { method: 'GET' }, { fetch: f, signal });
}

export async function createWebhook(
  input: CreateWebhookInput,
  f?: FetchFn,
): Promise<WebhookCreateResponse> {
  return request<WebhookCreateResponse>(
    '/v1/dash/webhooks',
    {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(input),
    },
    { fetch: f },
  );
}

export async function updateWebhook(
  id: string,
  input: UpdateWebhookInput,
  f?: FetchFn,
): Promise<WebhookSummary> {
  return request<WebhookSummary>(
    `/v1/dash/webhooks/${encodeURIComponent(id)}`,
    {
      method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(input),
    },
    { fetch: f },
  );
}

export async function deleteWebhook(id: string, f?: FetchFn): Promise<void> {
  await request<unknown>(
    `/v1/dash/webhooks/${encodeURIComponent(id)}`,
    { method: 'DELETE' },
    { fetch: f },
  );
}

export async function testWebhook(id: string, f?: FetchFn): Promise<void> {
  await request<unknown>(
    `/v1/dash/webhooks/${encodeURIComponent(id)}/test`,
    { method: 'POST' },
    { fetch: f },
  );
}

export async function getWebhookDeliveries(
  id: string,
  f?: FetchFn,
  signal?: AbortSignal,
): Promise<WebhookDeliveriesResponse> {
  return request<WebhookDeliveriesResponse>(
    `/v1/dash/webhooks/${encodeURIComponent(id)}/deliveries`,
    { method: 'GET' },
    { fetch: f, signal },
  );
}

// ---------- /v1/dash/settings/retention (audit retention policy) ----------
//
// Mirrors `server/src/rp_server/routers/dash_retention.py`. Admin-only on
// the server; the SPA hides the Retention sub-card for non-admins but the
// server is still the source of truth (403 on non-admin calls).

export interface RetentionConfig {
  retention_days: number;
  enabled: boolean;
  last_purge_at: string | null;
  last_purge_count: number | null;
  updated_by: string;
  updated_at: string;
  /** Lower bound surfaced from the server so the SPA need not hard-code it. */
  min_days: number;
  /** Upper bound surfaced from the server. */
  max_days: number;
}

export interface UpdateRetentionInput {
  retention_days?: number;
  enabled?: boolean;
}

export interface PurgeNowResult {
  deleted: number;
  retention_days: number;
  enabled: boolean;
}

export async function getRetentionConfig(
  f?: FetchFn,
  signal?: AbortSignal,
): Promise<RetentionConfig> {
  return request<RetentionConfig>(
    '/v1/dash/settings/retention',
    { method: 'GET' },
    { fetch: f, signal },
  );
}

export async function updateRetentionConfig(
  input: UpdateRetentionInput,
  f?: FetchFn,
): Promise<RetentionConfig> {
  return request<RetentionConfig>(
    '/v1/dash/settings/retention',
    {
      method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(input),
    },
    { fetch: f },
  );
}

export async function purgeRetentionNow(f?: FetchFn): Promise<PurgeNowResult> {
  return request<PurgeNowResult>(
    '/v1/dash/settings/retention/purge-now',
    { method: 'POST' },
    { fetch: f },
  );
}

// ---------- webhook deliveries (retry + reset failures) ----------

/**
 * Re-fire a previously recorded delivery. Server responds 202 + a small
 * envelope; the new outcome surfaces in the next deliveries poll.
 */
export interface RetryDeliveryResponse {
  status: string;
  webhook_id: string;
  retry_of: string;
}

export async function retryWebhookDelivery(
  webhookId: string,
  deliveryId: string,
  f?: FetchFn,
): Promise<RetryDeliveryResponse> {
  return request<RetryDeliveryResponse>(
    `/v1/dash/webhooks/${encodeURIComponent(webhookId)}/deliveries/${encodeURIComponent(
      deliveryId,
    )}/retry`,
    { method: 'POST' },
    { fetch: f },
  );
}

/**
 * Clear failure_count and re-enable a hook. Returns the updated summary
 * so callers can patch their cache without a refetch.
 */
export async function resetWebhookFailures(id: string, f?: FetchFn): Promise<WebhookSummary> {
  return request<WebhookSummary>(
    `/v1/dash/webhooks/${encodeURIComponent(id)}/reset-failures`,
    { method: 'POST' },
    { fetch: f },
  );
}

// Exported for unit tests — keeps URL serialisation honest with the
// backend contract (multi-value status / action, cursor-paged).
export const __testing = {
  buildCommandsQuery,
  buildAuditQuery,
};
