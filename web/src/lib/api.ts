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
