<script lang="ts">
  import { Command as CommandPrimitive } from 'bits-ui';
  import { cn } from '#lib/utils.ts';

  type Props = CommandPrimitive.ListProps;
  let { ref = $bindable(null), class: className, ...rest }: Props = $props();
</script>

<CommandPrimitive.List
  bind:ref
  class={cn('max-h-[60vh] overflow-x-hidden overflow-y-auto', className)}
  {...rest}
/>
