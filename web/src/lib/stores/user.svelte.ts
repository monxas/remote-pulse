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
    /**
     * Check whether the signed-in user is permitted to perform ``action``
     * within ``scope`` (a group name, or undefined for global checks).
     *
     * Admins always pass. Otherwise the row-level grant must match either
     * a wildcard scope (``*``) or the exact group requested. Mirrors the
     * server-side ``user_has_permission`` helper in
     * ``rp_server/permissions.py`` so the client gate stays in lockstep
     * with the actual enforcement.
     *
     * NOTE: this is a UX gate only — the server is the source of truth.
     * Hiding a button does not protect the endpoint; the gate exists so
     * non-permitted users don't see affordances they can't use.
     */
    hasPermission(action: string, scope?: string): boolean {
      if (!value) return false;
      if (value.user_role === 'admin') return true;
      const perms = value.permissions ?? [];
      return perms.some(
        (p) => p.action === action && (p.scope === '*' || (scope !== undefined && p.scope === scope)),
      );
    },
  };
}

export const userStore = createUserStore();
