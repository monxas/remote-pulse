<script lang="ts">
  import { LogOut } from '@lucide/svelte';
  import { userStore } from '$lib/stores/user.svelte';

  function initials(email: string | null | undefined): string {
    if (!email) return '?';
    const at = email.indexOf('@');
    const local = at > 0 ? email.slice(0, at) : email;
    const parts = local.split(/[._-]/).filter(Boolean);
    if (parts.length >= 2) {
      return ((parts[0]?.[0] ?? '') + (parts[1]?.[0] ?? '')).toUpperCase();
    }
    return local.slice(0, 2).toUpperCase();
  }
</script>

{#if userStore.value}
  <div class="flex items-center gap-2">
    <span
      class="inline-flex size-7 items-center justify-center rounded-full bg-accent-bg font-mono text-[10px] font-semibold text-accent-text"
      aria-hidden="true"
      title={userStore.value.user_email ?? undefined}
    >
      {initials(userStore.value.user_email)}
    </span>
    <a
      class="touch-target inline-flex items-center justify-center gap-1 rounded-md px-2 py-1 text-xs text-muted hover:bg-subtle hover:text-default"
      href="/auth/logout"
      data-sveltekit-reload
      title="Sign out"
      aria-label="Sign out"
    >
      <LogOut class="size-3.5" aria-hidden="true" />
      <span class="sr-only sm:not-sr-only">Sign out</span>
    </a>
  </div>
{/if}
