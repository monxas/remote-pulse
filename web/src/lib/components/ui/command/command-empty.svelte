<script lang="ts">
  import { Command as CommandPrimitive } from 'bits-ui';
  import { cn } from '$lib/utils';

  type Props = CommandPrimitive.EmptyProps;
  let { ref = $bindable(null), class: className, ...rest }: Props = $props();
</script>

<CommandPrimitive.Empty
  bind:ref
  class={cn('py-6 text-center text-sm text-muted', className)}
  {...rest}
/>
