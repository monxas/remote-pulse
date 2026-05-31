/**
 * Bulk command dispatcher.
 *
 * Fan-outs a single command payload across N hosts as N parallel
 * `POST /v1/dash/commands` requests and tracks per-host outcomes so the
 * UI can render a progress + per-host result table.
 *
 * Rationale for client-side fan-out:
 *   The dashboard backend accepts `host_ids: string[]` in a single
 *   `issueDashCommand` call, but the `command.issue` permission is
 *   evaluated per-host on the server. If any host in the batch is
 *   permission-denied, today's behaviour is to 4xx the whole request,
 *   which gives operators a worse experience than per-host failures.
 *
 *   By splitting the batch on the client we get:
 *     - partial success (2 OK + 1 forbidden surfaces honestly),
 *     - granular error messages (per-host),
 *     - no backend changes for v1 of bulk actions.
 *
 *   When a future server endpoint adds per-host failure semantics, swap
 *   the implementation of `dispatchBulk` and keep the consumer API.
 */

import { issueDashCommand, ApiError, type IssueCommandInput } from '$lib/api';

export type BulkItemStatus = 'pending' | 'in-flight' | 'success' | 'error' | 'cancelled';

export interface BulkItem {
  host_id: string;
  hostname: string;
  status: BulkItemStatus;
  /** Human-readable error message when `status === 'error'`. */
  error?: string;
  /** HTTP status when the failure came from the server. */
  httpStatus?: number;
  /** Server-issued command id when `status === 'success'`. */
  command_id?: string;
}

/** Bounded concurrency for the fan-out. v1.0.14 used unbounded
 * `Promise.all`, which made "Cancel remaining" a no-op (everything was
 * already in-flight on the network). v1.0.15 runs a small pool so an
 * abort mid-flight actually drops the queued tail. Four is the sweet
 * spot: high enough to feel snappy on a 20-host bulk, low enough that
 * a 100-host bulk still has meaningful "remaining to cancel" room. */
const DEFAULT_CONCURRENCY = 4;

export interface BulkDispatchInput {
  hostIds: ReadonlyArray<string>;
  hostnamesById: Readonly<Record<string, string>>;
  command_type: string;
  command_payload: Record<string, unknown>;
  reason?: string;
  requires_approval?: boolean;
  /** Aborts queued (not-yet-sent) requests. In-flight requests are
   * allowed to settle — the server has already received them, and a
   * mid-flight 4xx surfaces as a confusing "did it issue or not?" so we
   * deliberately do NOT signal the underlying fetch. */
  signal?: AbortSignal;
  /** Override concurrency for tests; default 4. */
  concurrency?: number;
}

export interface BulkDispatchResult {
  items: BulkItem[];
  okCount: number;
  errorCount: number;
  cancelledCount: number;
}

/**
 * Single-host issue. Extracted so tests can mock `issueDashCommand`
 * cleanly via `vi.mock('$lib/api', ...)`. Returns a result tuple so the
 * caller can update the corresponding item without throwing.
 */
async function issueOne(
  host_id: string,
  base: Omit<IssueCommandInput, 'host_ids'>,
): Promise<Pick<BulkItem, 'status' | 'error' | 'httpStatus' | 'command_id'>> {
  try {
    const resp = await issueDashCommand({ ...base, host_ids: [host_id] });
    const cmd = resp.commands[0];
    return { status: 'success', command_id: cmd?.id };
  } catch (err) {
    if (err instanceof ApiError) {
      return {
        status: 'error',
        httpStatus: err.status,
        error:
          err.status === 403
            ? 'Permission denied (no command.issue grant on this host).'
            : err.message,
      };
    }
    return {
      status: 'error',
      error: err instanceof Error ? err.message : 'Unknown error',
    };
  }
}

/**
 * Fan-out across all host ids with bounded concurrency; resolves once
 * every request has settled (or been cancelled). `onItemChange` fires
 * for every per-host state transition (in-flight → success / error /
 * cancelled). The Svelte dialog uses this to drive its per-host status
 * badges in real time.
 *
 * Cancellation (`input.signal`):
 *   - Only the *queued* tail is dropped — anything already in-flight
 *     gets to settle, because the server has accepted it and the
 *     command row would otherwise leak as "did it actually issue?".
 *   - Cancelled items emit `status: 'cancelled'` so the UI can render
 *     a distinct chip and the operator sees exactly which hosts were
 *     skipped.
 */
export async function dispatchBulk(
  input: BulkDispatchInput,
  onItemChange: (item: BulkItem) => void,
): Promise<BulkDispatchResult> {
  const base = {
    command_type: input.command_type,
    command_payload: input.command_payload,
    reason: input.reason,
    requires_approval: input.requires_approval,
  };

  const concurrency = Math.max(1, input.concurrency ?? DEFAULT_CONCURRENCY);
  const signal = input.signal;
  const results: BulkItem[] = new Array(input.hostIds.length);

  // Worker-pool driven by a shared cursor — each worker pulls the next
  // host id, checks the signal, then either issues or marks cancelled.
  // This is a tiny bit fiddlier than `Promise.all(map)` but it's the
  // only way to actually skip work once an abort fires.
  let cursor = 0;

  async function worker(): Promise<void> {
    while (true) {
      const i = cursor;
      cursor += 1;
      if (i >= input.hostIds.length) return;
      const host_id = input.hostIds[i]!;
      const hostname = input.hostnamesById[host_id] ?? host_id;

      if (signal?.aborted) {
        const item: BulkItem = { host_id, hostname, status: 'cancelled' };
        results[i] = item;
        onItemChange(item);
        continue;
      }

      onItemChange({ host_id, hostname, status: 'in-flight' });
      const outcome = await issueOne(host_id, base);
      const item: BulkItem = { host_id, hostname, ...outcome };
      results[i] = item;
      onItemChange(item);
    }
  }

  const workers = Array.from({ length: Math.min(concurrency, input.hostIds.length) }, () =>
    worker(),
  );
  await Promise.all(workers);

  return {
    items: results,
    okCount: results.filter((i) => i.status === 'success').length,
    errorCount: results.filter((i) => i.status === 'error').length,
    cancelledCount: results.filter((i) => i.status === 'cancelled').length,
  };
}

/** Initial pending state — convenient seed for the dialog's reactive state. */
export function seedItems(
  hostIds: ReadonlyArray<string>,
  hostnamesById: Readonly<Record<string, string>>,
): BulkItem[] {
  return hostIds.map((id) => ({
    host_id: id,
    hostname: hostnamesById[id] ?? id,
    status: 'pending' as const,
  }));
}
