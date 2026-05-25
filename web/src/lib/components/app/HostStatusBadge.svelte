<script lang="ts">
  import { cn } from '$lib/utils';
  import type { HostStatus } from '$lib/api';
  import { formatRelative } from '$lib/utils/relative-time';

  type Props = {
    status: HostStatus;
    lastSeenSecondsAgo?: number | null;
    showLabel?: boolean;
    class?: string;
  };
  const { status, lastSeenSecondsAgo, showLabel = true, class: className }: Props = $props();

  const labels: Record<HostStatus, string> = {
    online: 'Online',
    stale: 'Stale',
    offline: 'Offline',
    unknown: 'Unknown',
  };

  const dotColor: Record<HostStatus, string> = {
    online: 'bg-success',
    stale: 'bg-warn',
    offline: 'bg-danger',
    unknown: 'bg-muted',
  };

  const textColor: Record<HostStatus, string> = {
    online: 'text-success-text',
    stale: 'text-warn-text',
    offline: 'text-danger-text',
    unknown: 'text-muted',
  };

  const srLabel = $derived(
    lastSeenSecondsAgo === null || lastSeenSecondsAgo === undefined
      ? labels[status]
      : `${labels[status]}, last seen ${formatRelative(lastSeenSecondsAgo)}`,
  );
</script>

<span
  class={cn('inline-flex items-center gap-1.5 text-xs font-medium', textColor[status], className)}
  role="status"
  aria-label={srLabel}
>
  <span class={cn('inline-block size-2 rounded-full', dotColor[status])} aria-hidden="true"></span>
  {#if showLabel}
    <span>{labels[status]}</span>
  {/if}
</span>
