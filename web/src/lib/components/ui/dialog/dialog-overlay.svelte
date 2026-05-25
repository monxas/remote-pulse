<script lang="ts">
  import { Dialog as DialogPrimitive } from 'bits-ui';
  import { cn } from '$lib/utils';

  type Props = DialogPrimitive.OverlayProps;
  let { ref = $bindable(null), class: className, ...rest }: Props = $props();
</script>

<DialogPrimitive.Overlay
  bind:ref
  class={cn('fixed inset-0 z-50 bg-black/60 backdrop-blur-sm', className)}
  {...rest}
/>
