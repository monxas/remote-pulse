<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { HTMLAttributes } from 'svelte/elements';
  import { cn } from '$lib/utils';

  type Props = HTMLAttributes<HTMLDivElement> & { children?: Snippet };
  let { class: className, children, ...rest }: Props = $props();
</script>

<div
  class={cn(
    'mt-4 flex flex-col-reverse gap-2 sm:flex-row sm:items-center sm:justify-end',
    className,
  )}
  {...rest}
>
  {@render children?.()}
</div>
