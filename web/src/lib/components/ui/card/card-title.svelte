<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { HTMLAttributes } from 'svelte/elements';
  import { cn } from '$lib/utils';

  type Props = HTMLAttributes<HTMLHeadingElement> & {
    children?: Snippet;
    level?: 1 | 2 | 3 | 4 | 5 | 6;
  };
  // Default level is `2` because Cards are typically the highest-level
  // grouping under a page `<h1>`. axe-core's `heading-order` rule fires
  // on `h1 → h3` skips, which used to dock /settings 0.06 on Lighthouse.
  // Pass `level={3}` explicitly when nesting a Card under another Card.
  let { class: className, level = 2, children, ...rest }: Props = $props();
</script>

{#if level === 1}
  <h1
    class={cn('text-lg leading-none font-semibold tracking-tight text-default', className)}
    {...rest}
  >
    {@render children?.()}
  </h1>
{:else if level === 2}
  <h2
    class={cn('text-lg leading-none font-semibold tracking-tight text-default', className)}
    {...rest}
  >
    {@render children?.()}
  </h2>
{:else}
  <h3
    class={cn('text-lg leading-none font-semibold tracking-tight text-default', className)}
    {...rest}
  >
    {@render children?.()}
  </h3>
{/if}
