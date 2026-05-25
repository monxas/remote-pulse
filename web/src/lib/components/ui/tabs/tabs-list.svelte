<script lang="ts">
  import { Tabs as TabsPrimitive } from 'bits-ui';
  import { cn } from '$lib/utils';

  type Props = TabsPrimitive.ListProps;
  let { ref = $bindable(null), class: className, ...rest }: Props = $props();
</script>

<TabsPrimitive.List
  bind:ref
  class={cn(
    'inline-flex h-9 items-center justify-start gap-1 rounded-md border border-border-default bg-subtle p-1 text-muted',
    className,
  )}
  {...rest}
/>
