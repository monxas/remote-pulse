<script lang="ts">
  import { Tabs as TabsPrimitive } from 'bits-ui';
  import { cn } from '$lib/utils';

  type Props = TabsPrimitive.RootProps;
  let { ref = $bindable(null), class: className, value = $bindable(), ...rest }: Props = $props();
</script>

<TabsPrimitive.Root bind:ref bind:value class={cn('flex flex-col gap-3', className)} {...rest} />
