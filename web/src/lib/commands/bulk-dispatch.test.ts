import { describe, it, expect, vi, beforeEach } from 'vitest';

// Hoist the mock so importing `bulk-dispatch` (which transitively imports
// `$lib/api`) resolves to our stub. We import the symbols we need by
// name to keep the mock object small + typed.
const issueDashCommandMock = vi.fn();

vi.mock('$lib/api', async () => {
  // Keep the real `ApiError` class so the dispatcher's `instanceof` check
  // still works against mocked rejections.
  const actual = await vi.importActual<typeof import('$lib/api')>('$lib/api');
  return {
    ...actual,
    issueDashCommand: (...args: unknown[]) => issueDashCommandMock(...args),
  };
});

import { ApiError } from '$lib/api';
import { dispatchBulk, seedItems, type BulkItem } from './bulk-dispatch';

describe('seedItems', () => {
  it('returns one pending item per host id, mapping hostnames when known', () => {
    const items = seedItems(['h1', 'h2'], { h1: 'alpha', h2: 'beta' });
    expect(items).toEqual([
      { host_id: 'h1', hostname: 'alpha', status: 'pending' },
      { host_id: 'h2', hostname: 'beta', status: 'pending' },
    ]);
  });

  it('falls back to the id when a hostname is missing', () => {
    const items = seedItems(['h1'], {});
    expect(items[0]?.hostname).toBe('h1');
  });
});

describe('dispatchBulk', () => {
  beforeEach(() => {
    issueDashCommandMock.mockReset();
  });

  it('fires one POST per host and reports all-success', async () => {
    issueDashCommandMock.mockImplementation(async (body: { host_ids: string[] }) => ({
      commands: body.host_ids.map((id) => ({ id: `cmd-${id}` })),
    }));

    const events: string[] = [];
    const result = await dispatchBulk(
      {
        hostIds: ['h1', 'h2', 'h3'],
        hostnamesById: { h1: 'a', h2: 'b', h3: 'c' },
        command_type: 'shell',
        command_payload: { cmd: 'uptime' },
      },
      (item) => events.push(`${item.hostname}:${item.status}`),
    );

    expect(issueDashCommandMock).toHaveBeenCalledTimes(3);
    // Each call should target a single host (client-side fan-out).
    for (const call of issueDashCommandMock.mock.calls) {
      expect((call[0] as { host_ids: string[] }).host_ids).toHaveLength(1);
    }
    expect(result.okCount).toBe(3);
    expect(result.errorCount).toBe(0);
    // Each host emits at least two events: in-flight and success.
    expect(events.filter((e) => e.endsWith(':in-flight'))).toHaveLength(3);
    expect(events.filter((e) => e.endsWith(':success'))).toHaveLength(3);
  });

  it('surfaces partial failures with per-host error messages', async () => {
    issueDashCommandMock.mockImplementation(async (body: { host_ids: string[] }) => {
      const id = body.host_ids[0];
      if (id === 'h2') {
        throw new ApiError(403, 'forbidden');
      }
      return { commands: [{ id: `cmd-${id}` }] };
    });

    const result = await dispatchBulk(
      {
        hostIds: ['h1', 'h2', 'h3'],
        hostnamesById: { h1: 'a', h2: 'b', h3: 'c' },
        command_type: 'shell',
        command_payload: { cmd: 'uptime' },
      },
      () => {},
    );

    expect(result.okCount).toBe(2);
    expect(result.errorCount).toBe(1);
    const failed = result.items.find((i) => i.host_id === 'h2');
    expect(failed?.status).toBe('error');
    expect(failed?.httpStatus).toBe(403);
    // We rewrite 403 into a friendlier permission message for the UI.
    expect(failed?.error).toMatch(/Permission denied/);
  });

  it('does not throw when every host fails', async () => {
    issueDashCommandMock.mockRejectedValue(new ApiError(500, 'boom'));
    const result = await dispatchBulk(
      {
        hostIds: ['h1', 'h2'],
        hostnamesById: { h1: 'a', h2: 'b' },
        command_type: 'shell',
        command_payload: { cmd: 'uptime' },
      },
      () => {},
    );
    expect(result.okCount).toBe(0);
    expect(result.errorCount).toBe(2);
    expect(result.items.every((i) => i.status === 'error')).toBe(true);
  });

  it('honours an AbortSignal — queued hosts settle as cancelled, in-flight finish', async () => {
    // Block resolution of the first request until we manually flip a
    // deferred promise. With concurrency=1 this lets us assert that the
    // *queued* tail (h2, h3) is dropped while the *in-flight* h1 still
    // gets to settle, matching the production semantics.
    let releaseFirst: () => void = () => {};
    const firstStarted = new Promise<void>((resolve) => {
      issueDashCommandMock.mockImplementationOnce(async (body: { host_ids: string[] }) => {
        resolve();
        await new Promise<void>((r) => (releaseFirst = r));
        return { commands: [{ id: `cmd-${body.host_ids[0]}` }] };
      });
    });
    issueDashCommandMock.mockImplementation(async (body: { host_ids: string[] }) => ({
      commands: [{ id: `cmd-${body.host_ids[0]}` }],
    }));

    const ctl = new AbortController();
    const events: BulkItem[] = [];
    const promise = dispatchBulk(
      {
        hostIds: ['h1', 'h2', 'h3'],
        hostnamesById: { h1: 'a', h2: 'b', h3: 'c' },
        command_type: 'shell',
        command_payload: { cmd: 'uptime' },
        signal: ctl.signal,
        concurrency: 1,
      },
      (item) => events.push({ ...item }),
    );

    // Wait until h1 has started, then abort and release h1 so the pool
    // drains. With the abort tripped, h2 and h3 must NOT trigger
    // issueDashCommand at all.
    await firstStarted;
    ctl.abort();
    releaseFirst();

    const result = await promise;
    expect(issueDashCommandMock).toHaveBeenCalledTimes(1);
    expect(result.okCount).toBe(1);
    expect(result.cancelledCount).toBe(2);
    expect(result.items.map((i) => i.status)).toEqual(['success', 'cancelled', 'cancelled']);
  });

  it('aborting before any request starts cancels every host', async () => {
    const ctl = new AbortController();
    ctl.abort();
    const result = await dispatchBulk(
      {
        hostIds: ['h1', 'h2'],
        hostnamesById: { h1: 'a', h2: 'b' },
        command_type: 'shell',
        command_payload: { cmd: 'uptime' },
        signal: ctl.signal,
      },
      () => {},
    );
    expect(issueDashCommandMock).not.toHaveBeenCalled();
    expect(result.cancelledCount).toBe(2);
    expect(result.okCount).toBe(0);
    expect(result.errorCount).toBe(0);
  });
});
