<script lang="ts">
  import { cn } from '$lib/utils';
  import type { SseState } from '$lib/queries/sse.svelte';

  type Props = { state: SseState; class?: string };
  const { state, class: className }: Props = $props();

  const labels: Record<SseState, string> = {
    idle: 'Idle',
    connecting: 'Connecting',
    open: 'Live',
    reconnecting: 'Reconnecting…',
    disabled: 'Polling',
    failed: 'Offline',
  };

  const dot: Record<SseState, string> = {
    idle: 'bg-muted',
    connecting: 'bg-warn animate-pulse',
    open: 'bg-success animate-pulse',
    reconnecting: 'bg-warn animate-pulse',
    disabled: 'bg-muted',
    failed: 'bg-danger',
  };

  const tone: Record<SseState, string> = {
    idle: 'text-muted',
    connecting: 'text-warn-text',
    open: 'text-success-text',
    reconnecting: 'text-warn-text',
    disabled: 'text-muted',
    failed: 'text-danger-text',
  };
</script>

<span
  class={cn('inline-flex items-center gap-1.5 text-xs font-medium', tone[state], className)}
  role="status"
  aria-live="polite"
  aria-label={`Live stream: ${labels[state]}`}
>
  <span class={cn('inline-block size-2 rounded-full', dot[state])} aria-hidden="true"></span>
  <span>{labels[state]}</span>
</span>
