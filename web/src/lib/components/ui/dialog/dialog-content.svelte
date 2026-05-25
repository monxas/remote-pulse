<script lang="ts">
  import { Dialog as DialogPrimitive } from 'bits-ui';
  import { X } from '@lucide/svelte';
  import type { Snippet } from 'svelte';
  import { cn } from '$lib/utils';
  import DialogOverlay from './dialog-overlay.svelte';

  type Props = DialogPrimitive.ContentProps & {
    side?: 'center' | 'bottom';
    showClose?: boolean;
    portal?: boolean;
    closeLabel?: string;
    children?: Snippet;
  };
  let {
    ref = $bindable(null),
    class: className,
    side = 'center',
    showClose = true,
    portal = true,
    closeLabel = 'Close',
    children,
    ...rest
  }: Props = $props();

  const positioning: Record<'center' | 'bottom', string> = {
    center:
      'fixed top-1/2 left-1/2 z-50 max-h-[90vh] w-[calc(100vw-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 overflow-auto',
    bottom:
      'fixed bottom-0 left-0 right-0 z-50 max-h-[90vh] w-full overflow-auto rounded-t-xl sm:bottom-auto sm:top-1/2 sm:left-1/2 sm:max-w-lg sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-xl',
  };
</script>

{#snippet body()}
  <DialogOverlay />
  <DialogPrimitive.Content
    bind:ref
    class={cn(
      positioning[side],
      'border border-border-default bg-elevated p-4 text-default shadow-xl sm:p-6 rounded-xl',
      className,
    )}
    {...rest}
  >
    {@render children?.()}
    {#if showClose}
      <DialogPrimitive.Close
        class="absolute right-3 top-3 inline-flex h-7 w-7 items-center justify-center rounded-md text-muted transition-colors hover:bg-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        aria-label={closeLabel}
      >
        <X class="size-4" aria-hidden="true" />
      </DialogPrimitive.Close>
    {/if}
  </DialogPrimitive.Content>
{/snippet}

{#if portal}
  <DialogPrimitive.Portal>
    {@render body()}
  </DialogPrimitive.Portal>
{:else}
  {@render body()}
{/if}
