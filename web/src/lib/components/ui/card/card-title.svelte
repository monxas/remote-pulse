<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { HTMLAttributes } from 'svelte/elements';
  import { cn } from '$lib/utils';

  type Props = HTMLAttributes<HTMLHeadingElement> & {
    children?: Snippet;
    level?: 1 | 2 | 3 | 4 | 5 | 6;
  };
  let { class: className, level = 3, children, ...rest }: Props = $props();
</script>

{#if level === 1}
  <h1 class={cn('text-lg leading-none font-semibold tracking-tight', className)} {...rest}>
    {@render children?.()}
  </h1>
{:else if level === 2}
  <h2 class={cn('text-lg leading-none font-semibold tracking-tight', className)} {...rest}>
    {@render children?.()}
  </h2>
{:else}
  <h3 class={cn('text-lg leading-none font-semibold tracking-tight', className)} {...rest}>
    {@render children?.()}
  </h3>
{/if}
