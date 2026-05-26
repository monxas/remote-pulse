<script lang="ts">
  import { cn } from '$lib/utils';

  type Props = {
    value: string;
    options?: readonly string[];
    onchange: (next: string) => void;
    /** Optional aria-label override. */
    label?: string;
  };
  const {
    value,
    options = ['5m', '15m', '1h', '6h', '24h', '7d'] as const,
    onchange,
    label = 'Window',
  }: Props = $props();
</script>

<div
  role="radiogroup"
  aria-label={label}
  class="inline-flex items-center gap-0 rounded-md border border-border-default bg-subtle p-0.5 text-xs"
>
  {#each options as opt (opt)}
    {@const selected = opt === value}
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      class={cn(
        'touch-target inline-flex items-center justify-center rounded-sm px-2.5 py-1 font-mono transition-colors',
        selected ? 'bg-elevated text-default shadow-sm' : 'text-muted hover:text-default',
      )}
      onclick={() => onchange(opt)}
    >
      {opt}
    </button>
  {/each}
</div>
