<script lang="ts" module>
  export type ButtonVariant = 'default' | 'secondary' | 'outline' | 'ghost' | 'danger' | 'link';
  export type ButtonSize = 'sm' | 'md' | 'lg' | 'icon';
</script>

<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { HTMLAnchorAttributes, HTMLButtonAttributes } from 'svelte/elements';
  import { cn } from '$lib/utils';

  // Props extend both anchor + button HTML attribute sets (minus the
  // ones we own / disambiguate) so the `<button>` branch can spread
  // `{...rest}` without TS griping that `onclick`/`oncopy`/etc. have
  // `HTMLAnchorElement`-typed handlers. Native HTML lets `data-*`,
  // `aria-*`, `name`, `value`, `formaction`, `id`, `style`, … through
  // on both elements; the (small) cost is that genuinely
  // element-specific attrs (`href`/`target`/`download` on anchors;
  // `name`/`value`/`formaction` on buttons) become loosely typed when
  // the caller passes them to the "wrong" branch. The runtime
  // template still picks the correct branch via the `href` discriminator.
  type Props = {
    variant?: ButtonVariant;
    size?: ButtonSize;
    children?: Snippet;
    class?: string;
    href?: string;
    type?: HTMLButtonAttributes['type'];
    onclick?: HTMLButtonAttributes['onclick'];
    disabled?: boolean;
    'aria-label'?: string;
    title?: string;
  } & Omit<HTMLAnchorAttributes, 'class' | 'type' | 'href' | 'onclick'> &
    Omit<HTMLButtonAttributes, 'class' | 'type' | 'onclick' | 'disabled'>;

  let {
    variant = 'default',
    size = 'md',
    class: className,
    children,
    href,
    type = 'button',
    onclick,
    disabled,
    'aria-label': ariaLabel,
    title,
    ...rest
  }: Props = $props();

  const variants: Record<ButtonVariant, string> = {
    default:
      'bg-accent text-accent-contrast hover:bg-accent-hover focus-visible:ring-2 focus-visible:ring-ring',
    secondary:
      'bg-subtle text-default hover:bg-hover focus-visible:ring-2 focus-visible:ring-ring border border-border-default',
    outline:
      'border border-border-default bg-transparent text-default hover:bg-subtle focus-visible:ring-2 focus-visible:ring-ring',
    ghost: 'bg-transparent text-default hover:bg-subtle',
    danger:
      'bg-danger text-accent-contrast hover:opacity-90 focus-visible:ring-2 focus-visible:ring-ring',
    link: 'bg-transparent text-accent-text underline-offset-4 hover:underline',
  };
  const sizes: Record<ButtonSize, string> = {
    sm: 'h-8 px-3 text-xs',
    md: 'h-9 px-4 text-sm',
    lg: 'h-10 px-6 text-sm',
    icon: 'h-9 w-9',
  };

  const base =
    'inline-flex select-none items-center justify-center gap-2 rounded-md font-medium transition-colors disabled:pointer-events-none disabled:opacity-50 focus-visible:outline-none';
</script>

{#if href}
  <a
    class={cn(base, variants[variant], sizes[size], className)}
    {href}
    aria-label={ariaLabel}
    {title}
    {...rest}
  >
    {@render children?.()}
  </a>
{:else}
  <button
    class={cn(base, variants[variant], sizes[size], className)}
    {...rest}
    {type}
    {onclick}
    {disabled}
    aria-label={ariaLabel}
    {title}
  >
    {@render children?.()}
  </button>
{/if}
