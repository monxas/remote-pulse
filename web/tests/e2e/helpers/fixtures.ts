/**
 * Deterministic fixture factories used by the Phase-5 flow specs.
 *
 * Shapes mirror `src/lib/api.ts`. We keep them as plain factories (no
 * deep-freezes, no class wrappers) so individual specs can spread + tweak.
 */

export interface HostFixture {
  id: string;
  hostname: string;
  group_name: string;
  status: 'online' | 'stale' | 'offline' | 'unknown';
  last_seen_at: string | null;
  last_seen_seconds_ago: number | null;
  os_family: string | null;
  agent_version: string | null;
  tailscale_ip: string | null;
  current: {
    cpu_pct: number | null;
    mem_pct: number | null;
    load_1m: number | null;
    uptime_s: number | null;
  };
  sparkline: {
    window_s: number;
    bucket_s: number;
    ts: number[];
    cpu_pct: (number | null)[];
    mem_pct: (number | null)[];
  };
}

export function makeHost(overrides: Partial<HostFixture> = {}): HostFixture {
  const nowS = Math.floor(Date.now() / 1000);
  const ts = Array.from({ length: 6 }, (_, i) => nowS - (5 - i) * 10);
  return {
    id: 'host-1',
    hostname: 'rp-server-1',
    group_name: 'prod',
    status: 'online',
    last_seen_at: new Date(nowS * 1000).toISOString(),
    last_seen_seconds_ago: 3,
    os_family: 'linux',
    agent_version: '1.0.4',
    tailscale_ip: '100.64.0.10',
    current: { cpu_pct: 12.5, mem_pct: 41.2, load_1m: 0.23, uptime_s: 3_600 * 72 },
    sparkline: {
      window_s: 60,
      bucket_s: 10,
      ts,
      cpu_pct: [10, 11, 12, 13, 12, 12.5],
      mem_pct: [40, 41, 41, 41, 41, 41.2],
    },
    ...overrides,
  };
}

export function makeOverview(overrides: Partial<{
  total: number;
  online: number;
  stale: number;
  offline: number;
  pending_approvals: number;
  online_pct: number;
  online_pct_24h_ago: number;
}> = {}) {
  return {
    total: 3,
    online: 1,
    stale: 1,
    offline: 1,
    pending_approvals: 0,
    online_pct: 33.3,
    online_pct_24h_ago: 33.3,
    ...overrides,
  };
}

export interface CommandFixture {
  id: string;
  host_id: string;
  host_hostname: string;
  issued_by: string;
  command_type: string;
  command_payload: Record<string, unknown>;
  status:
    | 'pending-approval'
    | 'approved'
    | 'queued'
    | 'running'
    | 'succeeded'
    | 'failed'
    | 'timeout'
    | 'rejected'
    | 'canceled';
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

export function makeCommand(overrides: Partial<CommandFixture> = {}): CommandFixture {
  return {
    id: 'cmd-1',
    host_id: 'host-1',
    host_hostname: 'rp-server-1',
    issued_by: 'admin@test.local',
    command_type: 'shell',
    command_payload: { cmd: 'uptime', timeout_s: 30 },
    status: 'pending-approval',
    issued_at: new Date().toISOString(),
    completed_at: null,
    exit_code: null,
    stdout: null,
    stderr: null,
    duration_ms: null,
    human_approved: false,
    approved_by: null,
    rejected_reason: null,
    ...overrides,
  };
}
