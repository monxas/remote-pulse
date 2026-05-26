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

export type BulkItemStatus = 'pending' | 'in-flight' | 'success' | 'error';

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

export interface BulkDispatchInput {
  hostIds: ReadonlyArray<string>;
  hostnamesById: Readonly<Record<string, string>>;
  command_type: string;
  command_payload: Record<string, unknown>;
  reason?: string;
  requires_approval?: boolean;
}

export interface BulkDispatchResult {
  items: BulkItem[];
  okCount: number;
  errorCount: number;
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
 * Fan-out across all host ids; resolves once every request has settled.
 * `onItemChange` fires twice per host: once when its request starts
 * (status `in-flight`) and once when it settles. The Svelte dialog uses
 * this to drive its per-host status badges in real time.
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

  const promises = input.hostIds.map(async (host_id) => {
    const hostname = input.hostnamesById[host_id] ?? host_id;
    onItemChange({ host_id, hostname, status: 'in-flight' });
    const outcome = await issueOne(host_id, base);
    const item: BulkItem = { host_id, hostname, ...outcome };
    onItemChange(item);
    return item;
  });

  const items = await Promise.all(promises);
  return {
    items,
    okCount: items.filter((i) => i.status === 'success').length,
    errorCount: items.filter((i) => i.status === 'error').length,
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
