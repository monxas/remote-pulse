<script lang="ts">
  import { Tabs as TabsPrimitive } from 'bits-ui';
  import { cn } from '#lib/utils.ts';

  type Props = TabsPrimitive.ContentProps;
  let { ref = $bindable(null), class: className, ...rest }: Props = $props();
</script>

<TabsPrimitive.Content
  bind:ref
  class={cn('focus-visible:ring-ring focus-visible:ring-2 focus-visible:outline-none', className)}
  {...rest}
/>
