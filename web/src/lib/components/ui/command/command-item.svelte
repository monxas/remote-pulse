<script lang="ts">
  import { Command as CommandPrimitive } from 'bits-ui';
  import { cn } from '$lib/utils';

  type Props = CommandPrimitive.ItemProps;
  let { ref = $bindable(null), class: className, ...rest }: Props = $props();
</script>

<CommandPrimitive.Item
  bind:ref
  class={cn(
    'relative flex cursor-pointer select-none items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-none',
    'data-[selected=true]:bg-subtle data-[selected=true]:text-default',
    'data-[disabled=true]:pointer-events-none data-[disabled=true]:opacity-50',
    className,
  )}
  {...rest}
/>
