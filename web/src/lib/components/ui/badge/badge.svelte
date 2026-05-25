<script lang="ts" module>
  export type BadgeVariant =
    | 'default'
    | 'secondary'
    | 'outline'
    | 'success'
    | 'warn'
    | 'danger'
    | 'muted';
</script>

<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { HTMLAttributes } from 'svelte/elements';
  import { cn } from '$lib/utils';

  type Props = HTMLAttributes<HTMLSpanElement> & {
    variant?: BadgeVariant;
    children?: Snippet;
  };
  let { class: className, variant = 'default', children, ...rest }: Props = $props();

  const variants: Record<BadgeVariant, string> = {
    default: 'border-transparent bg-accent-bg text-accent-text',
    secondary: 'border-transparent bg-subtle text-default',
    outline: 'border-border-default text-default',
    success: 'border-transparent bg-success-bg text-success-text',
    warn: 'border-transparent bg-warn-bg text-warn-text',
    danger: 'border-transparent bg-danger-bg text-danger-text',
    muted: 'border-transparent bg-subtle text-muted',
  };
</script>

<span
  class={cn(
    'inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium',
    variants[variant],
    className,
  )}
  {...rest}
>
  {@render children?.()}
</span>
