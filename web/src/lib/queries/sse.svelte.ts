/**
 * Live-stream bridge for `/v1/dash/stream` (Server-Sent Events).
 *
 * Phase-1 + Phase-2 contract:
 *   - host.heartbeat          -> invalidate ['hosts']
 *   - host.status_change      -> invalidate ['hosts'] + ['overview']
 *   - command.issued          -> invalidate ['commands'] + ['audit']
 *   - command.status_change   -> invalidate ['commands'] + ['commands', id]
 *                                          + ['audit'] + ['overview']
 *   - approval.created        -> invalidate ['approvals'] + ['audit']
 *                                          + ['overview']
 *   - approval.resolved       -> invalidate ['approvals'] + ['commands']
 *                                          + ['audit'] + ['overview']
 *   - gap                     -> server-side replay of missed events after
 *                                a reconnect (consumed transparently, not
 *                                surfaced to the UI history)
 *
 * Event payloads (best-effort): when JSON we look for `{ command_id }` or
 * `{ id }` to surface a more granular invalidation on the per-id detail
 * query. Anything else falls back to a broad invalidation, which the
 * QueryClient batches efficiently in-memory.
 *
 * If the endpoint is missing (404) we fall back to the polling intervals
 * baked into the query hooks — no crash, just a warning.
 *
 * Reconnect strategy
 * ------------------
 * - Exponential backoff: 1s → 2s → 4s → 8s → 16s → 30s (capped).
 * - Backoff resets to 1s after the connection has been open and stable
 *   for at least `STABLE_WINDOW_MS` (5s).
 * - After `MAX_RETRIES` (10) consecutive failures we stop trying and
 *   emit a single persistent toast prompting the user to refresh.
 * - When the server adds `id:` fields to its events, EventSource sets
 *   `Last-Event-ID` on reconnect automatically; the server uses that
 *   header to replay the events the client missed (best-effort, capped
 *   by the in-memory ring buffer on the publisher side).
 */

import { onDestroy } from 'svelte';
import type { QueryClient } from '@tanstack/svelte-query';
import { toast } from 'svelte-sonner';

export type SseState = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'disabled' | 'failed';

export interface SseEvent {
  /** Event name from the SSE `event:` line (e.g. `host.heartbeat`). */
  type: string;
  /** Parsed JSON payload if the server emitted JSON, else the raw string. */
  data: unknown;
  /** Client-side receive timestamp (epoch ms). */
  ts: number;
  /** Server-assigned monotonic id (best-effort) — used for gap detection. */
  id?: string | null;
}

export type SseEventListener = (event: SseEvent) => void;

const STREAM_PATH = '/v1/dash/stream';
const INITIAL_BACKOFF_MS = 1_000;
const MAX_BACKOFF_MS = 30_000;
const STABLE_WINDOW_MS = 5_000;
const MAX_RETRIES = 10;
const HISTORY = 50;

/**
 * Compute the next backoff delay using exponential growth capped at
 * {@link MAX_BACKOFF_MS}. Exported for unit-test coverage of the
 * doubling sequence (1s, 2s, 4s, 8s, 16s, 30s, 30s, …).
 */
export function nextBackoff(current: number): number {
  return Math.min(current * 2, MAX_BACKOFF_MS);
}

export interface LiveStream {
  readonly state: SseState;
  readonly events: ReadonlyArray<SseEvent>;
  readonly lastEventId: string | null;
  /** Add a listener that fires for every event (after invalidation). */
  on(listener: SseEventListener): () => void;
  close(): void;
}

/**
 * Boot the SSE bridge. The hook owns its own connection lifecycle and
 * registers an `onDestroy` cleanup, so the caller does not have to
 * dispose explicitly — though `close()` is still exposed for tests.
 */
export function useLiveStream(client: QueryClient): LiveStream {
  let state = $state<SseState>('idle');
  const events = $state<SseEvent[]>([]);
  let lastEventId = $state<string | null>(null);

  let source: EventSource | null = null;
  let backoff = INITIAL_BACKOFF_MS;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let stableTimer: ReturnType<typeof setTimeout> | null = null;
  let toastedFailure = false;
  let disposed = false;
  let retryCount = 0;

  // This Set is never read from a reactive context — it's just a
  // subscriber registry for SSE event listeners. Disable the lint that
  // would otherwise push us toward SvelteSet (which adds reactivity
  // overhead we don't need here).
  // eslint-disable-next-line svelte/prefer-svelte-reactivity
  const listeners: Set<SseEventListener> = new Set();

  function pushEvent(type: string, raw: string, id: string | null): void {
    let data: unknown = raw;
    try {
      data = JSON.parse(raw);
    } catch {
      // raw string is fine
    }
    const evt: SseEvent = { type, data, ts: Date.now(), id };
    if (id) lastEventId = id;

    // The `gap` event is a server-side replay marker for events the
    // client missed during a disconnect. We don't surface it in the
    // history (it'd just clutter the activity feed) but we DO process
    // the inner payload so caches stay fresh.
    if (type === 'gap') {
      // Expected shape: { events: [{ type, data, id, ts }] }
      const replayed = extractReplayedEvents(data);
      for (const inner of replayed) {
        pushEvent(inner.type, JSON.stringify(inner.data ?? {}), inner.id ?? null);
      }
      return;
    }

    events.push(evt);
    while (events.length > HISTORY) events.shift();

    // Try to extract a command id from the payload so we can scope per-id
    // detail-query invalidations precisely. We accept `command_id` or `id`.
    const commandId = extractId(data);

    switch (type) {
      case 'host.heartbeat':
        void client.invalidateQueries({ queryKey: ['hosts'] });
        break;
      case 'host.status_change':
        void client.invalidateQueries({ queryKey: ['hosts'] });
        void client.invalidateQueries({ queryKey: ['overview'] });
        break;
      case 'command.issued':
        void client.invalidateQueries({ queryKey: ['commands'] });
        void client.invalidateQueries({ queryKey: ['audit'] });
        void client.invalidateQueries({ queryKey: ['overview'] });
        break;
      case 'command.status_change':
        void client.invalidateQueries({ queryKey: ['commands'] });
        if (commandId) {
          void client.invalidateQueries({
            queryKey: ['commands', 'detail', commandId],
          });
        }
        void client.invalidateQueries({ queryKey: ['audit'] });
        void client.invalidateQueries({ queryKey: ['overview'] });
        break;
      case 'approval.created':
        void client.invalidateQueries({ queryKey: ['approvals'] });
        void client.invalidateQueries({ queryKey: ['audit'] });
        void client.invalidateQueries({ queryKey: ['overview'] });
        break;
      case 'approval.resolved':
        void client.invalidateQueries({ queryKey: ['approvals'] });
        void client.invalidateQueries({ queryKey: ['commands'] });
        if (commandId) {
          void client.invalidateQueries({
            queryKey: ['commands', 'detail', commandId],
          });
        }
        void client.invalidateQueries({ queryKey: ['audit'] });
        void client.invalidateQueries({ queryKey: ['overview'] });
        break;
      default:
        break;
    }

    // Fan out to subscribed listeners (recent-activity widget, toaster).
    for (const fn of listeners) {
      try {
        fn(evt);
      } catch (err) {
        console.warn('[remote-pulse] SSE listener threw', err);
      }
    }
  }

  function extractId(payload: unknown): string | null {
    if (!payload || typeof payload !== 'object') return null;
    const obj = payload as Record<string, unknown>;
    const candidate = obj.command_id ?? obj.id;
    return typeof candidate === 'string' && candidate.length > 0 ? candidate : null;
  }

  function extractReplayedEvents(
    payload: unknown,
  ): Array<{ type: string; data: unknown; id?: string | null }> {
    if (!payload || typeof payload !== 'object') return [];
    const obj = payload as { events?: unknown };
    if (!Array.isArray(obj.events)) return [];
    const out: Array<{ type: string; data: unknown; id?: string | null }> = [];
    for (const raw of obj.events) {
      if (!raw || typeof raw !== 'object') continue;
      const r = raw as Record<string, unknown>;
      const t = typeof r.type === 'string' ? r.type : null;
      if (!t) continue;
      out.push({
        type: t,
        data: r.data ?? null,
        id: typeof r.id === 'string' ? r.id : null,
      });
    }
    return out;
  }

  function scheduleReconnect(): void {
    if (disposed) return;
    if (retryCount >= MAX_RETRIES) {
      state = 'failed';
      if (!toastedFailure) {
        toastedFailure = true;
        toast.error('Real-time disconnected', {
          description: 'Refresh the page to restore live updates.',
          duration: Infinity,
        });
      }
      return;
    }
    state = 'reconnecting';
    if (reconnectTimer !== null) clearTimeout(reconnectTimer);
    const delay = Math.min(backoff, MAX_BACKOFF_MS);
    reconnectTimer = setTimeout(() => {
      backoff = nextBackoff(backoff);
      retryCount += 1;
      void open();
    }, delay);
  }

  function clearStableTimer(): void {
    if (stableTimer !== null) {
      clearTimeout(stableTimer);
      stableTimer = null;
    }
  }

  async function probe(): Promise<boolean> {
    // HEAD probe to detect "not deployed yet" without burning EventSource
    // reconnect cycles on a 404.
    try {
      const res = await fetch(STREAM_PATH, { method: 'HEAD', credentials: 'same-origin' });
      return res.status !== 404;
    } catch {
      return true; // network error: let EventSource retry path handle it
    }
  }

  async function open(): Promise<void> {
    if (disposed) return;
    state = 'connecting';
    if (!(await probe())) {
      state = 'disabled';
      console.warn(
        '[remote-pulse] /v1/dash/stream not available — falling back to polling-only mode',
      );
      return;
    }

    try {
      source = new EventSource(STREAM_PATH, { withCredentials: true });
    } catch (err) {
      console.warn('[remote-pulse] failed to open SSE', err);
      scheduleReconnect();
      return;
    }

    source.onopen = () => {
      state = 'open';
      // Don't reset backoff immediately — a server that closes the
      // connection after `accept` would otherwise keep us in a tight
      // 1s loop. Only reset once the link has been stable for a while.
      clearStableTimer();
      stableTimer = setTimeout(() => {
        backoff = INITIAL_BACKOFF_MS;
        retryCount = 0;
        toastedFailure = false;
      }, STABLE_WINDOW_MS);
    };

    source.onerror = () => {
      // EventSource silently retries by default; we close + manage backoff
      // ourselves so the UI gets a clear "reconnecting" indicator.
      clearStableTimer();
      source?.close();
      source = null;
      scheduleReconnect();
    };

    // Generic catch-all (server may send unnamed messages)
    source.onmessage = (e) => pushEvent('message', e.data ?? '', e.lastEventId || null);

    // Named events from the backend contract
    const handle = (name: string) => (e: MessageEvent) =>
      pushEvent(name, e.data ?? '', e.lastEventId || null);
    for (const name of [
      'host.heartbeat',
      'host.status_change',
      'command.issued',
      'command.status_change',
      'approval.created',
      'approval.resolved',
      'gap',
    ]) {
      source.addEventListener(name, handle(name) as EventListener);
    }
  }

  function close(): void {
    disposed = true;
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    clearStableTimer();
    source?.close();
    source = null;
    state = 'idle';
  }

  function on(listener: SseEventListener): () => void {
    listeners.add(listener);
    return () => listeners.delete(listener);
  }

  // Open immediately. Caller is responsible for calling `close()` on
  // teardown (via `onDestroy` registered below).
  //
  // Skip the SSE stream entirely when running under the Lighthouse CI
  // bypass (build-time flag + `?_lh=1` query). Vite preview serves the
  // SPA shell for unknown paths so EventSource would log a `text/html`
  // MIME-type error to the console, dragging the best-practices score
  // below the budget. The bypass is tree-shaken out of release builds.
  const lhBypassActive =
    import.meta.env.VITE_LH_BYPASS === '1' &&
    typeof window !== 'undefined' &&
    new URL(window.location.href).searchParams.get('_lh') === '1';
  if (lhBypassActive) {
    state = 'disabled';
  } else {
    void open();
  }
  onDestroy(close);

  return {
    get state() {
      return state;
    },
    get events() {
      return events;
    },
    get lastEventId() {
      return lastEventId;
    },
    on,
    close,
  };
}
