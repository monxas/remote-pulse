<script lang="ts">
  import { Command as CommandPrimitive } from 'bits-ui';
  import { cn } from '#lib/utils.ts';

  type Props = CommandPrimitive.GroupProps & { heading?: string };
  let { ref = $bindable(null), class: className, heading, children, ...rest }: Props = $props();
</script>

<CommandPrimitive.Group
  bind:ref
  class={cn('text-default overflow-hidden p-1', className)}
  {...rest}
>
  {#if heading}
    <CommandPrimitive.GroupHeading class="text-muted px-2 py-1.5 text-xs font-medium">
      {heading}
    </CommandPrimitive.GroupHeading>
  {/if}
  <CommandPrimitive.GroupItems>
    {@render children?.()}
  </CommandPrimitive.GroupItems>
</CommandPrimitive.Group>
