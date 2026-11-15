<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { HTMLAttributes } from 'svelte/elements';
  import { cn } from '#lib/utils.ts';

  type Props = HTMLAttributes<HTMLParagraphElement> & { children?: Snippet };
  let { class: className, children, ...rest }: Props = $props();
</script>

<p class={cn('text-muted text-sm', className)} {...rest}>
  {@render children?.()}
</p>
