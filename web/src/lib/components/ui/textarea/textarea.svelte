<script lang="ts">
  import type { HTMLTextareaAttributes } from 'svelte/elements';
  import { cn } from '#lib/utils.ts';

  type Props = HTMLTextareaAttributes & { value?: string };
  let { class: className, value = $bindable(''), ...rest }: Props = $props();
</script>

<textarea
  class={cn(
    'border-border-default bg-base text-default placeholder:text-muted focus-visible:ring-ring flex min-h-20 w-full rounded-md border px-3 py-2 text-sm shadow-sm transition-colors focus-visible:ring-2 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50',
    'font-mono',
    className,
  )}
  bind:value
  {...rest}></textarea>
