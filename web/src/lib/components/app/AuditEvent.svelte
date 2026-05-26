<script lang="ts" module>
  import type { AuditAction, AuditTargetType } from '$lib/api';

  type Tone = 'success' | 'warn' | 'danger' | 'accent' | 'muted';

  const ACTION_TONE: Record<AuditAction, Tone> = {
    'command.issued': 'accent',
    'command.approved': 'success',
    'command.rejected': 'danger',
    'command.completed': 'success',
    'command.failed': 'danger',
    'host.enrolled': 'accent',
    'enrollment.token_issued': 'warn',
    'settings.group.create': 'accent',
    'settings.group.delete': 'danger',
    'settings.user.create': 'accent',
    'settings.user.update': 'warn',
    'settings.user.delete': 'danger',
  };

  const ACTION_LABEL: Record<AuditAction, string> = {
    'command.issued': 'issued command',
    'command.approved': 'approved command',
    'command.rejected': 'rejected command',
    'command.completed': 'command completed',
    'command.failed': 'command failed',
    'host.enrolled': 'enrolled host',
    'enrollment.token_issued': 'issued enrollment token',
    'settings.group.create': 'created group',
    'settings.group.delete': 'deleted group',
    'settings.user.create': 'created user',
    'settings.user.update': 'updated user',
    'settings.user.delete': 'deleted user',
  };

  export { ACTION_LABEL, ACTION_TONE };
</script>

<script lang="ts">
  import { resolve } from '$app/paths';
  import type { AuditEvent } from '$lib/api';
  import { cn } from '$lib/utils';
  import RelativeTime from './RelativeTime.svelte';

  type Props = { event: AuditEvent };
  const { event }: Props = $props();

  const dotClass: Record<Tone, string> = {
    success: 'bg-success',
    warn: 'bg-warn',
    danger: 'bg-danger',
    accent: 'bg-accent',
    muted: 'bg-muted',
  };
  const tone = $derived(ACTION_TONE[event.action]);

  function targetHref(t: AuditTargetType, id: string): string | null {
    if (t === 'command') return resolve('/commands/[id]', { id });
    if (t === 'host') return resolve('/hosts/[id]', { id });
    return null;
  }

  const href = $derived(targetHref(event.target_type, event.target_id));
  const metadataPretty = $derived(
    Object.keys(event.metadata).length === 0 ? '' : JSON.stringify(event.metadata, null, 2),
  );
</script>

<li class="relative flex gap-3 pl-1">
  <div class="relative flex w-6 shrink-0 flex-col items-center">
    <span
      class={cn('mt-1.5 size-2.5 shrink-0 rounded-full ring-4 ring-base', dotClass[tone])}
      aria-hidden="true"
    ></span>
    <span class="mt-1 w-px flex-1 bg-border-subtle" aria-hidden="true"></span>
  </div>
  <div class="flex-1 pb-4 text-sm">
    <p>
      <span class="font-mono text-default">{event.actor}</span>
      <span class="text-muted">{ACTION_LABEL[event.action]}</span>
      {#if href}
        <!-- href is produced via $app/paths' resolve(); rule can't trace through the helper. -->
        <!-- eslint-disable-next-line svelte/no-navigation-without-resolve -->
        <a class="font-mono text-accent-text hover:underline" {href}>{event.target_label}</a>
      {:else}
        <span class="font-mono">{event.target_label}</span>
      {/if}
    </p>
    <p class="text-xs text-muted">
      <RelativeTime iso={event.ts} class="font-mono" />
      <span class="ml-2 font-mono">{event.action}</span>
    </p>
    {#if metadataPretty}
      <details class="mt-1 rounded-md border border-border-subtle bg-subtle text-xs">
        <summary class="cursor-pointer px-2 py-1 text-muted">metadata</summary>
        <pre class="overflow-x-auto px-2 pb-2 font-mono text-xs">{metadataPretty}</pre>
      </details>
    {/if}
  </div>
</li>
