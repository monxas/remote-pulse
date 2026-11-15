<script lang="ts">
  import { Tabs as TabsPrimitive } from 'bits-ui';
  import { cn } from '#lib/utils.ts';

  type Props = TabsPrimitive.ListProps;
  let { ref = $bindable(null), class: className, ...rest }: Props = $props();
</script>

<TabsPrimitive.List
  bind:ref
  class={cn(
    'border-border-default bg-subtle text-muted inline-flex h-9 items-center justify-start gap-1 rounded-md border p-1',
    className,
  )}
  {...rest}
/>
