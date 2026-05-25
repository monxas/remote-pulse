<script lang="ts">
  import { Toaster as Sonner, type ToasterProps } from 'svelte-sonner';
  import { themeStore } from '$lib/stores/theme.svelte';

  let { ...rest }: ToasterProps = $props();
</script>

<Sonner
  theme={themeStore.resolved}
  class="toaster group"
  position="bottom-right"
  toastOptions={{
    classes: {
      toast:
        'group toast group-[.toaster]:bg-elevated group-[.toaster]:text-default group-[.toaster]:border-border-default group-[.toaster]:shadow-lg',
      description: 'group-[.toast]:text-muted',
      actionButton: 'group-[.toast]:bg-accent group-[.toast]:text-accent-contrast',
      cancelButton: 'group-[.toast]:bg-subtle group-[.toast]:text-muted',
    },
  }}
  {...rest}
/>
