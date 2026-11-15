<script lang="ts">
  import { Command as CommandPrimitive } from 'bits-ui';
  import { cn } from '#lib/utils.ts';

  type Props = CommandPrimitive.RootProps;
  let { ref = $bindable(null), class: className, ...rest }: Props = $props();
</script>

<CommandPrimitive.Root
  bind:ref
  class={cn(
    'bg-elevated text-default flex h-full w-full flex-col overflow-hidden rounded-md',
    className,
  )}
  {...rest}
/>
