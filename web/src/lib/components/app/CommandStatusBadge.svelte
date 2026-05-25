<script lang="ts" module>
  import type { CommandStatus } from '$lib/api';

  type Tone = 'success' | 'warn' | 'danger' | 'muted' | 'accent';

  export const STATUS_LABEL: Record<CommandStatus, string> = {
    'pending-approval': 'Pending approval',
    approved: 'Approved',
    queued: 'Queued',
    running: 'Running',
    succeeded: 'Succeeded',
    failed: 'Failed',
    timeout: 'Timed out',
    rejected: 'Rejected',
    canceled: 'Canceled',
  };

  export const STATUS_TONE: Record<CommandStatus, Tone> = {
    'pending-approval': 'warn',
    approved: 'accent',
    queued: 'accent',
    running: 'accent',
    succeeded: 'success',
    failed: 'danger',
    timeout: 'danger',
    rejected: 'danger',
    canceled: 'muted',
  };
</script>

<script lang="ts">
  import { cn } from '$lib/utils';

  type Props = {
    status: CommandStatus;
    showDot?: boolean;
    class?: string;
  };
  const { status, showDot = true, class: className }: Props = $props();

  const toneClasses: Record<Tone, { bg: string; dot: string }> = {
    success: { bg: 'bg-success-bg text-success-text', dot: 'bg-success' },
    warn: { bg: 'bg-warn-bg text-warn-text', dot: 'bg-warn' },
    danger: { bg: 'bg-danger-bg text-danger-text', dot: 'bg-danger' },
    accent: { bg: 'bg-accent-bg text-accent-text', dot: 'bg-accent' },
    muted: { bg: 'bg-subtle text-muted', dot: 'bg-muted' },
  };

  const tone = $derived(STATUS_TONE[status]);
  const label = $derived(STATUS_LABEL[status]);
  const pulse = $derived(status === 'running' || status === 'queued');
</script>

<span
  class={cn(
    'inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium',
    toneClasses[tone].bg,
    className,
  )}
  role="status"
  aria-label={`Command status: ${label}`}
>
  {#if showDot}
    <span
      class={cn(
        'inline-block size-1.5 rounded-full',
        toneClasses[tone].dot,
        pulse && 'animate-pulse',
      )}
      aria-hidden="true"
    ></span>
  {/if}
  <span>{label}</span>
</span>
