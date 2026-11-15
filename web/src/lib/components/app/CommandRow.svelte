<script lang="ts">
  import { ChevronRight, ExternalLink, RotateCw } from '@lucide/svelte';
  import { resolve } from '$app/paths';
  import { cn } from '#lib/utils.ts';
  import type { CommandRecord } from '#lib/api.ts';
  import { IN_FLIGHT_STATUSES } from '#lib/api.ts';
  import { Button } from '#lib/components/ui/button/index.ts';
  import CommandStatusBadge from './CommandStatusBadge.svelte';
  import RelativeTime from './RelativeTime.svelte';
  import { createRetryCommandMutation } from '#lib/queries/index.ts';

  type Props = {
    command: CommandRecord;
    defaultOpen?: boolean;
  };
  const { command, defaultOpen = false }: Props = $props();

  // Open state is intentionally seeded from the `defaultOpen` prop on
  // mount and then becomes locally controlled — toggling the row is a
  // UI-only concern.
  // svelte-ignore state_referenced_locally
  let open = $state(defaultOpen);

  const retry = createRetryCommandMutation();

  function summarisePayload(payload: Record<string, unknown>): string {
    if ('cmd' in payload && typeof payload.cmd === 'string') return payload.cmd;
    if ('script' in payload && typeof payload.script === 'string') {
      const args = Array.isArray(payload.args) ? ` ${payload.args.join(' ')}` : '';
      return `${payload.script}${args}`;
    }
    return JSON.stringify(payload);
  }

  const payloadSummary = $derived(summarisePayload(command.command_payload));
  const detailHref = $derived(resolve('/commands/[id]', { id: command.id }));
  const canRetry = $derived(
    command.status === 'failed' ||
      command.status === 'timeout' ||
      command.status === 'canceled' ||
      command.status === 'succeeded',
  );
  const isInFlight = $derived(IN_FLIGHT_STATUSES.has(command.status));
</script>

<li
  class="border-border-default bg-elevated rounded-lg border"
  data-testid="command-row"
  data-command-id={command.id}
>
  <button
    type="button"
    data-testid="command-row-toggle"
    class="hover:bg-hover focus-visible:ring-ring flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none"
    onclick={() => (open = !open)}
    aria-expanded={open}
    aria-controls={`cmd-body-${command.id}`}
  >
    <ChevronRight
      class={cn('text-muted size-4 shrink-0 transition-transform', open && 'rotate-90')}
      aria-hidden="true"
    />
    <CommandStatusBadge status={command.status} />
    <span class="text-muted shrink-0 font-mono text-xs">{command.command_type}</span>
    <span class="text-default min-w-0 flex-1 truncate font-mono text-sm" title={payloadSummary}>
      {payloadSummary}
    </span>
    <span class="text-muted hidden font-mono text-xs sm:inline">{command.host_hostname}</span>
    <RelativeTime iso={command.issued_at} class="text-muted ml-auto shrink-0 font-mono text-xs" />
  </button>

  {#if open}
    <div
      id={`cmd-body-${command.id}`}
      class="border-border-subtle space-y-3 border-t px-3 py-3 text-sm"
    >
      <dl class="grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-4">
        <div>
          <dt class="text-muted">Host</dt>
          <dd class="font-mono">{command.host_hostname}</dd>
        </div>
        <div>
          <dt class="text-muted">Issued by</dt>
          <dd class="font-mono">{command.issued_by}</dd>
        </div>
        <div>
          <dt class="text-muted">Approved by</dt>
          <dd class="font-mono">{command.approved_by ?? '—'}</dd>
        </div>
        <div>
          <dt class="text-muted">Exit code</dt>
          <dd class="font-mono">{command.exit_code ?? '—'}</dd>
        </div>
        <div>
          <dt class="text-muted">Duration</dt>
          <dd class="font-mono">
            {command.duration_ms === null ? '—' : `${command.duration_ms}ms`}
          </dd>
        </div>
        <div>
          <dt class="text-muted">Completed</dt>
          <dd class="font-mono">
            <RelativeTime iso={command.completed_at} />
          </dd>
        </div>
      </dl>

      {#if command.rejected_reason}
        <div class="border-danger bg-danger-bg text-danger-text rounded-md border p-2 text-xs">
          <span class="font-medium">Rejected:</span>
          {command.rejected_reason}
        </div>
      {/if}

      {#if command.stdout || command.stderr}
        <div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {#if command.stdout}
            <details open class="border-border-default bg-base rounded-md border">
              <summary class="text-muted cursor-pointer px-2 py-1 text-xs font-medium">
                stdout
              </summary>
              <pre
                class="max-h-64 overflow-auto px-2 pb-2 font-mono text-xs break-words whitespace-pre-wrap">{command.stdout}</pre>
            </details>
          {/if}
          {#if command.stderr}
            <details open class="border-border-default bg-base rounded-md border">
              <summary class="text-danger-text cursor-pointer px-2 py-1 text-xs font-medium">
                stderr
              </summary>
              <pre
                class="max-h-64 overflow-auto px-2 pb-2 font-mono text-xs break-words whitespace-pre-wrap">{command.stderr}</pre>
            </details>
          {/if}
        </div>
      {/if}

      <div class="flex flex-wrap items-center gap-2">
        <Button href={detailHref} size="sm" variant="outline">
          <ExternalLink class="size-3.5" aria-hidden="true" />
          Open details
        </Button>
        {#if canRetry}
          <Button
            size="sm"
            data-testid="command-retry-btn"
            onclick={() => $retry.mutate(command.id)}
            disabled={$retry.isPending}
          >
            <RotateCw
              class={cn('size-3.5', $retry.isPending && 'animate-spin')}
              aria-hidden="true"
            />
            Retry
          </Button>
        {/if}
        {#if isInFlight}
          <span class="text-muted text-xs">In-flight commands cannot be cancelled yet.</span>
        {/if}
      </div>
    </div>
  {/if}
</li>
