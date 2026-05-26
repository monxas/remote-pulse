<script lang="ts">
  /**
   * Headless component that subscribes to the live SSE stream and
   * surfaces toast notifications for high-signal events.
   *
   * Triggered (toast + entry in RecentActivityWidget):
   *   - `command.status_change` with status in {failed, timeout, rejected}
   *     → destructive toast with a click-through to the command detail
   *   - `approval.created` → info toast with a click-through to /approvals
   *   - `host.status_change` transitioning to `offline` → warning toast
   *
   * NOT surfaced as toast (recorded in widget only):
   *   - `host.heartbeat` (too frequent)
   *   - `host.status_change → online` (positive, not urgent)
   *   - `command.issued`, `approval.resolved`, etc.
   *
   * The component renders nothing — it just owns the listener lifetime.
   */
  import { onMount } from 'svelte';
  import { toast } from 'svelte-sonner';
  import { goto } from '$app/navigation';
  import { resolve } from '$app/paths';
  import { getLiveStream } from '$lib/queries/live-context';
  import type { SseEvent } from '$lib/queries/sse.svelte';

  const FAILED_STATUSES = new Set(['failed', 'timeout', 'rejected']);

  const live = getLiveStream();

  function readString(obj: unknown, key: string): string | null {
    if (!obj || typeof obj !== 'object') return null;
    const v = (obj as Record<string, unknown>)[key];
    return typeof v === 'string' && v.length > 0 ? v : null;
  }

  function hostLabel(payload: unknown): string {
    return (
      readString(payload, 'hostname') ??
      readString(payload, 'host_hostname') ??
      readString(payload, 'host_id') ??
      'a host'
    );
  }

  function commandLabel(payload: unknown): string {
    return readString(payload, 'command_type') ?? readString(payload, 'action') ?? 'Command';
  }

  function handle(evt: SseEvent): void {
    const data = evt.data;
    switch (evt.type) {
      case 'command.status_change': {
        const status = readString(data, 'status');
        if (!status || !FAILED_STATUSES.has(status)) return;
        const commandId = readString(data, 'command_id');
        const host = hostLabel(data);
        const exit = readString(data, 'exit_code') ?? `exit ${status}`;
        toast.error(`Command ${status} on ${host}`, {
          description: exit,
          action: commandId
            ? {
                label: 'View',
                onClick: () => {
                  // eslint-disable-next-line svelte/no-navigation-without-resolve
                  void goto(resolve(`/commands/${commandId}`) as `/${string}`);
                },
              }
            : undefined,
        });
        return;
      }
      case 'approval.created': {
        const host = hostLabel(data);
        const cmd = commandLabel(data);
        toast.info(`Approval needed for ${cmd} on ${host}`, {
          action: {
            label: 'Review',
            onClick: () => {
              // eslint-disable-next-line svelte/no-navigation-without-resolve
              void goto(resolve('/approvals') as `/${string}`);
            },
          },
        });
        return;
      }
      case 'host.status_change': {
        const to = readString(data, 'to');
        if (to !== 'offline') return;
        const host = hostLabel(data);
        const hostId = readString(data, 'host_id');
        toast.warning(`${host} went offline`, {
          action: hostId
            ? {
                label: 'View',
                onClick: () => {
                  // eslint-disable-next-line svelte/no-navigation-without-resolve
                  void goto(resolve(`/hosts/${hostId}`) as `/${string}`);
                },
              }
            : undefined,
        });
        return;
      }
      default:
        return;
    }
  }

  onMount(() => {
    if (!live) return;
    return live.on(handle);
  });
</script>
