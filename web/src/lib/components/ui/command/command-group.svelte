<script lang="ts">
  import { Command as CommandPrimitive } from 'bits-ui';
  import { cn } from '$lib/utils';

  type Props = CommandPrimitive.GroupProps & { heading?: string };
  let { ref = $bindable(null), class: className, heading, children, ...rest }: Props = $props();
</script>

<CommandPrimitive.Group
  bind:ref
  class={cn('overflow-hidden p-1 text-default', className)}
  {...rest}
>
  {#if heading}
    <CommandPrimitive.GroupHeading class="px-2 py-1.5 text-xs font-medium text-muted">
      {heading}
    </CommandPrimitive.GroupHeading>
  {/if}
  <CommandPrimitive.GroupItems>
    {@render children?.()}
  </CommandPrimitive.GroupItems>
</CommandPrimitive.Group>
