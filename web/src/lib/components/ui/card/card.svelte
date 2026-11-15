<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { HTMLAttributes } from 'svelte/elements';
  import { cn } from '#lib/utils.ts';

  type Props = HTMLAttributes<HTMLDivElement> & { children?: Snippet };
  let { class: className, children, ...rest }: Props = $props();
</script>

<div
  class={cn(
    'border-border-default bg-elevated text-default rounded-lg border shadow-sm',
    className,
  )}
  {...rest}
>
  {@render children?.()}
</div>
