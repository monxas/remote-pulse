<script lang="ts">
  import { Switch as SwitchPrimitive } from 'bits-ui';
  import { cn } from '#lib/utils.ts';

  type Props = SwitchPrimitive.RootProps;
  let {
    ref = $bindable(null),
    class: className,
    checked = $bindable(false),
    ...rest
  }: Props = $props();
</script>

<SwitchPrimitive.Root
  bind:ref
  bind:checked
  class={cn(
    'peer relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full border border-transparent transition-colors',
    'focus-visible:ring-ring focus-visible:ring-2 focus-visible:outline-none',
    'data-[state=checked]:bg-accent data-[state=unchecked]:bg-subtle',
    'disabled:cursor-not-allowed disabled:opacity-50',
    className,
  )}
  {...rest}
>
  <SwitchPrimitive.Thumb
    class={cn(
      'bg-elevated pointer-events-none block size-4 rounded-full shadow ring-0 transition-transform',
      'data-[state=checked]:translate-x-4 data-[state=unchecked]:translate-x-0.5',
    )}
  />
</SwitchPrimitive.Root>
