<script lang="ts">
  import type { HTMLTextareaAttributes } from 'svelte/elements';
  import { cn } from '$lib/utils';

  type Props = HTMLTextareaAttributes & { value?: string };
  let { class: className, value = $bindable(''), ...rest }: Props = $props();
</script>

<textarea
  class={cn(
    'flex min-h-20 w-full rounded-md border border-border-default bg-base px-3 py-2 text-sm text-default shadow-sm transition-colors placeholder:text-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50',
    'font-mono',
    className,
  )}
  bind:value
  {...rest}
></textarea>
