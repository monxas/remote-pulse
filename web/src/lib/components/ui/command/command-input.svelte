<script lang="ts">
  import { Command as CommandPrimitive } from 'bits-ui';
  import { Search } from '@lucide/svelte';
  import { cn } from '#lib/utils.ts';

  type Props = CommandPrimitive.InputProps;
  let { ref = $bindable(null), class: className, value = $bindable(''), ...rest }: Props = $props();
</script>

<div class="border-border-subtle flex items-center border-b px-3" data-cmdk-input-wrapper="">
  <Search class="text-muted mr-2 size-4 shrink-0" aria-hidden="true" />
  <CommandPrimitive.Input
    bind:ref
    bind:value
    class={cn(
      'text-default placeholder:text-muted flex h-10 w-full bg-transparent py-2 text-sm outline-none disabled:cursor-not-allowed disabled:opacity-50',
      className,
    )}
    {...rest}
  />
</div>
