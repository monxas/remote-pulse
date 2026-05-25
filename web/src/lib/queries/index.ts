/**
 * Typed query hooks for the Phase-1 dashboard.
 *
 * svelte-query v5 accepts either a static options object or a Svelte
 * `Readable<options>`. To stay reactive against Svelte 5 runes that live
 * in components, we expose helpers that consume a Svelte `Readable<Params>`
 * (the caller wires the readable to runes inside a `$effect`).
 *
 * Query keys are namespaced so the SSE invalidator can target precisely
 * (`['overview']`, `['hosts', ...]`, `['host', id]`, `['timeseries', id]`).
 */

import { derived, readable, type Readable } from 'svelte/store';
import { createQuery } from '@tanstack/svelte-query';
import {
  getDashHosts,
  getDashOverview,
  getDashTimeseries,
  type DashOverview,
  type HostStatus,
  type HostsList,
  type HostSummary,
  type TimeseriesPayload,
} from '$lib/api';

// ---- query keys ----
export const qk = {
  overview: () => ['overview'] as const,
  hosts: (params: HostsParams = {}) => ['hosts', params] as const,
  hostsAll: () => ['hosts'] as const,
  host: (hostId: string) => ['host', hostId] as const,
  timeseries: (hostId: string, params: TimeseriesParams) => ['timeseries', hostId, params] as const,
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
// No params, so static options are fine.
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

// ---- ergonomic helper: wrap a value-returning accessor into a Readable ----
// The caller MUST call this within a Svelte component (so the underlying
// reactive read happens in the component's render scope). The accessor is
// invoked once on subscribe; updates flow via a writable backed by a
// `$effect` inside the consuming component (see queries/reactive.svelte.ts).
export function staticReadable<T>(value: T): Readable<T> {
  return readable(value);
}
