<script lang="ts">
  import { Command as CommandPrimitive } from 'bits-ui';
  import { Search } from '@lucide/svelte';
  import { cn } from '$lib/utils';

  type Props = CommandPrimitive.InputProps;
  let { ref = $bindable(null), class: className, value = $bindable(''), ...rest }: Props = $props();
</script>

<div class="flex items-center border-b border-border-subtle px-3" data-cmdk-input-wrapper="">
  <Search class="mr-2 size-4 shrink-0 text-muted" aria-hidden="true" />
  <CommandPrimitive.Input
    bind:ref
    bind:value
    class={cn(
      'flex h-10 w-full bg-transparent py-2 text-sm text-default outline-none placeholder:text-muted disabled:cursor-not-allowed disabled:opacity-50',
      className,
    )}
    {...rest}
  />
</div>
