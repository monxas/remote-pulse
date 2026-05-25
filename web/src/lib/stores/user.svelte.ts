import type { AuthMe } from '$lib/api';

/**
 * Reactive user session container backed by a Svelte 5 rune `$state`.
 *
 * The root `+layout.ts` calls `/auth/me` and pushes the response in here
 * once during boot. Components subscribe by reading `userStore.value`.
 */
function createUserStore() {
  let value = $state<AuthMe | null>(null);
  return {
    get value() {
      return value;
    },
    set(next: AuthMe | null) {
      value = next;
    },
    clear() {
      value = null;
    },
  };
}

export const userStore = createUserStore();
