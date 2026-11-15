<script lang="ts">
  import { Dialog as DialogPrimitive } from 'bits-ui';
  import { cn } from '#lib/utils.ts';

  type Props = DialogPrimitive.TitleProps;
  let { ref = $bindable(null), class: className, ...rest }: Props = $props();
</script>

<DialogPrimitive.Title
  bind:ref
  class={cn('text-lg leading-none font-semibold tracking-tight', className)}
  {...rest}
/>
