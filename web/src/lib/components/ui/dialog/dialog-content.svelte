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

  // Positioning. The `center` variant becomes a bottom-sheet on
  // mobile (<sm) so dialogs that include forms — and therefore the
  // virtual keyboard — anchor to the bottom of the viewport and keep
  // the inputs reachable. This matches iOS/Android native modal
  // patterns and avoids the centered-modal-keyboard-overlap trap that
  // plagued Phase 1.
  const positioning: Record<'center' | 'bottom', string> = {
    center:
      'fixed bottom-0 left-0 right-0 z-50 max-h-[90vh] w-full overflow-auto rounded-t-xl pb-safe sm:bottom-auto sm:top-1/2 sm:left-1/2 sm:max-w-lg sm:w-[calc(100vw-2rem)] sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-xl sm:pb-0',
    bottom:
      'fixed bottom-0 left-0 right-0 z-50 max-h-[90vh] w-full overflow-auto rounded-t-xl pb-safe sm:bottom-auto sm:top-1/2 sm:left-1/2 sm:max-w-lg sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-xl sm:pb-0',
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
        class="touch-target absolute right-2 top-2 inline-flex h-9 w-9 items-center justify-center rounded-md text-muted transition-colors hover:bg-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:right-3 sm:top-3 sm:h-7 sm:w-7"
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
