<script lang="ts">
  import { Tabs as TabsPrimitive } from 'bits-ui';
  import { cn } from '$lib/utils';

  type Props = TabsPrimitive.TriggerProps;
  let { ref = $bindable(null), class: className, ...rest }: Props = $props();
</script>

<TabsPrimitive.Trigger
  bind:ref
  class={cn(
    'touch-target inline-flex items-center justify-center rounded-sm px-3 py-1 text-sm font-medium whitespace-nowrap transition-all',
    'focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
    'disabled:pointer-events-none disabled:opacity-50',
    'data-[state=active]:bg-elevated data-[state=active]:text-default data-[state=active]:shadow-sm',
    className,
  )}
  {...rest}
/>
