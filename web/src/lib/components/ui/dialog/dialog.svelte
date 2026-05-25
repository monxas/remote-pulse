<script lang="ts">
  import { Dialog as DialogPrimitive } from 'bits-ui';

  type Props = DialogPrimitive.RootProps;
  let { open = $bindable(false), onOpenChange, children, ...rest }: Props = $props();
</script>

<DialogPrimitive.Root bind:open {onOpenChange} {...rest}>
  {@render children?.()}
</DialogPrimitive.Root>
