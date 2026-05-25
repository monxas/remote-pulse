<script lang="ts">
  import { Sun, Moon, Monitor } from '@lucide/svelte';
  import { Button } from '$lib/components/ui/button';
  import { themeStore } from '$lib/stores/theme.svelte';

  function label(pref: typeof themeStore.pref): string {
    return pref === 'system' ? 'System theme' : pref === 'dark' ? 'Dark theme' : 'Light theme';
  }
</script>

<Button
  variant="ghost"
  size="icon"
  onclick={() => themeStore.cycle()}
  aria-label={`Toggle theme (currently ${label(themeStore.pref)})`}
  title={label(themeStore.pref)}
>
  {#if themeStore.pref === 'system'}
    <Monitor class="size-4" aria-hidden="true" />
  {:else if themeStore.pref === 'dark'}
    <Moon class="size-4" aria-hidden="true" />
  {:else}
    <Sun class="size-4" aria-hidden="true" />
  {/if}
</Button>
