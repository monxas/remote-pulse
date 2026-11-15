<script lang="ts">
  import type { HTMLInputAttributes } from 'svelte/elements';
  import { cn } from '#lib/utils.ts';

  type Props = HTMLInputAttributes & { value?: string };
  let { class: className, value = $bindable(''), ...rest }: Props = $props();
</script>

<input
  class={cn(
    'border-border-default bg-base text-default placeholder:text-muted focus-visible:ring-ring flex h-9 w-full rounded-md border px-3 py-1 text-sm shadow-sm transition-colors focus-visible:ring-2 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50',
    className,
  )}
  bind:value
  {...rest}
/>
