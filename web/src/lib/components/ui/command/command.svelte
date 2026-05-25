<script lang="ts">
  import { Command as CommandPrimitive } from 'bits-ui';
  import { cn } from '$lib/utils';

  type Props = CommandPrimitive.RootProps;
  let { ref = $bindable(null), class: className, ...rest }: Props = $props();
</script>

<CommandPrimitive.Root
  bind:ref
  class={cn(
    'flex h-full w-full flex-col overflow-hidden rounded-md bg-elevated text-default',
    className,
  )}
  {...rest}
/>
