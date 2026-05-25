import { QueryClient } from '@tanstack/svelte-query';

/**
 * Singleton QueryClient for the SPA. Phase-1 defaults:
 *  - staleTime 10s for overview/hosts (we have a 5s polling fallback when
 *    SSE is dead, plus an SSE-triggered invalidate).
 *  - 30s for timeseries (host-detail chart) — heavy query, cheap to refetch
 *    on demand via the window selector.
 *  - retry: 1 (network blips); we surface the error UI on the second fail.
 *  - refetchOnWindowFocus: true (matches operator expectations when the
 *    laptop wakes up).
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      gcTime: 5 * 60_000,
      retry: 1,
      refetchOnWindowFocus: true,
      refetchOnReconnect: true,
    },
  },
});
