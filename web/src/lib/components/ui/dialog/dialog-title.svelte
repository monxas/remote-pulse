<script lang="ts">
  import { Dialog as DialogPrimitive } from 'bits-ui';
  import { cn } from '$lib/utils';

  type Props = DialogPrimitive.TitleProps;
  let { ref = $bindable(null), class: className, ...rest }: Props = $props();
</script>

<DialogPrimitive.Title
  bind:ref
  class={cn('text-lg font-semibold leading-none tracking-tight', className)}
  {...rest}
/>
