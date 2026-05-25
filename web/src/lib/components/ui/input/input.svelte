<script lang="ts">
  import type { HTMLInputAttributes } from 'svelte/elements';
  import { cn } from '$lib/utils';

  type Props = HTMLInputAttributes & { value?: string };
  let { class: className, value = $bindable(''), ...rest }: Props = $props();
</script>

<input
  class={cn(
    'flex h-9 w-full rounded-md border border-border-default bg-base px-3 py-1 text-sm text-default shadow-sm transition-colors placeholder:text-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50',
    className,
  )}
  bind:value
  {...rest}
/>
