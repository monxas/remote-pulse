<script lang="ts">
  /**
   * Permissions modal for the Settings → Users tab.
   *
   * Lists row-level (action, scope) grants for a single user and lets an
   * admin grant or revoke them. Granting goes through the optimistic
   * mutations in $lib/queries so the table updates immediately and rolls
   * back on server error.
   *
   * Admins (target.role === 'admin') are noted as implicitly holding every
   * action — the table still shows any explicit rows that might exist for
   * historical reasons but the empty-state copy is different.
   */
  import { Loader2, Plus, ShieldCheck, Trash2, Key, Globe } from '@lucide/svelte';
  import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogDescription,
    DialogFooter,
  } from '$lib/components/ui/dialog';
  import { Button } from '$lib/components/ui/button';
  import { Badge } from '$lib/components/ui/badge';
  import {
    createGrantPermissionMutation,
    createRevokePermissionMutation,
    createUserPermissionsQuery,
  } from '$lib/queries';
  import { runeReadable } from '$lib/queries/reactive.svelte';
  import { userStore } from '$lib/stores/user.svelte';
  import { ALL_PERMISSION_ACTIONS, type PermissionAction, type SettingsUser } from '$lib/api';

  type Props = {
    open: boolean;
    onOpenChange: (next: boolean) => void;
    user: SettingsUser | null;
    /** Group names available as scopes for the new-grant form. */
    groups: string[];
  };

  let { open = $bindable(false), onOpenChange, user, groups }: Props = $props();

  // Reactive query: only fetches when we have a user selected.
  const userId = runeReadable(() => user?.id ?? '');
  const permsQuery = createUserPermissionsQuery(userId);

  // Pass the current admin's email so optimistic grants show "granted by you"
  // immediately. Falls back to a sentinel that we'll never display because
  // unauthenticated users can't reach this modal in the first place.
  const actorEmail = $derived(userStore.value?.user_email ?? 'optimistic');
  const grant = $derived(createGrantPermissionMutation(actorEmail));
  const revoke = createRevokePermissionMutation();

  // ---- Grant form state ----
  // Scope picker (v1.0.15): two modes — the wildcard `*` toggle (granting
  // ``action`` over every group) OR a multi-select of specific groups. The
  // backend's grant endpoint accepts ONE scope per call, so when the
  // operator selects N specific groups we fan out N POSTs on submit.
  // Rationale: typing scopes into a free-text Input let typos through
  // (a scope of "ops-prod" with a hyphen typo silently never matches);
  // chips reading from the live ``groups`` prop close that hole.
  let newAction = $state<PermissionAction>('command.issue');
  let wildcardSelected = $state<boolean>(true);
  let selectedGroups = $state<string[]>([]);

  $effect(() => {
    // Reset the form whenever the dialog opens against a fresh user so the
    // last selection doesn't leak between modals.
    if (open && user) {
      newAction = 'command.issue';
      wildcardSelected = true;
      selectedGroups = [];
    }
  });

  const isAdmin = $derived(user?.role === 'admin');

  /** Selecting the wildcard clears any specific picks; selecting a specific
   * group clears the wildcard. Mutually exclusive — matches the server's
   * scope semantics (``*`` is strictly broader than any named group). */
  function toggleWildcard(): void {
    wildcardSelected = true;
    selectedGroups = [];
  }

  function toggleGroup(name: string): void {
    wildcardSelected = false;
    selectedGroups = selectedGroups.includes(name)
      ? selectedGroups.filter((g) => g !== name)
      : [...selectedGroups, name];
    // If the operator unselects every chip, snap back to wildcard so the
    // Grant button never lands in an unsubmittable empty state.
    if (selectedGroups.length === 0) {
      wildcardSelected = true;
    }
  }

  /** The set of scopes the Grant button will issue, in order. */
  const scopesToGrant = $derived<string[]>(wildcardSelected ? ['*'] : selectedGroups);

  const canSubmit = $derived(scopesToGrant.length > 0 && !$grant.isPending);

  function submitGrant(e: Event): void {
    e.preventDefault();
    if (!user) return;
    // Fan out one mutation per selected scope. Each one is its own
    // optimistic update; the table refreshes as they settle. Duplicates
    // already-held by the user surface as the server's 409 — the
    // mutation's onError surfaces a toast and rolls back.
    for (const scope of scopesToGrant) {
      $grant.mutate({
        userId: user.id,
        input: { action: newAction, scope },
      });
    }
    // Reset the multi-select once dispatched so the next round doesn't
    // re-fire stale scopes.
    if (!wildcardSelected) {
      selectedGroups = [];
      wildcardSelected = true;
    }
  }

  function confirmRevoke(permissionId: string, label: string): void {
    if (!user) return;
    const ok = window.confirm(`Revoke "${label}"? The user loses this permission immediately.`);
    if (!ok) return;
    $revoke.mutate({ userId: user.id, permissionId });
  }
</script>

<Dialog bind:open onOpenChange={(o) => onOpenChange(o)}>
  <DialogContent class="max-w-2xl">
    <DialogHeader>
      <DialogTitle>
        <Key class="mr-2 inline size-4" aria-hidden="true" />
        Permissions
      </DialogTitle>
      <DialogDescription>
        {#if user}
          Fine-grained ACL for <span class="font-mono">{user.email}</span>. These rows layer on top
          of role + accessible groups.
        {:else}
          No user selected.
        {/if}
      </DialogDescription>
    </DialogHeader>

    {#if user}
      {#if isAdmin}
        <div
          class="flex items-start gap-2 rounded-md border border-border-default bg-subtle p-3 text-xs text-muted"
          role="note"
        >
          <ShieldCheck class="mt-0.5 size-4 shrink-0 text-accent" aria-hidden="true" />
          <span>
            This user is an <strong>admin</strong> and implicitly holds every action. Explicit grants
            below are honoured but redundant.
          </span>
        </div>
      {/if}

      <!-- Existing grants -->
      <div class="overflow-x-auto rounded-md border border-border-default">
        {#if $permsQuery.isPending}
          <div class="flex items-center gap-2 p-4 text-sm text-muted">
            <Loader2 class="size-4 animate-spin" aria-hidden="true" />
            Loading permissions…
          </div>
        {:else if $permsQuery.isError}
          <div class="p-4 text-sm text-danger-text">
            Failed to load: {$permsQuery.error?.message ?? 'unknown error'}
          </div>
        {:else if ($permsQuery.data?.permissions ?? []).length === 0}
          <div class="p-4 text-center text-sm text-muted">
            {isAdmin
              ? 'No explicit grants. (Admin already holds every action.)'
              : 'No explicit grants yet. Use the form below to grant one.'}
          </div>
        {:else}
          <table class="w-full text-sm">
            <thead class="border-b border-border-subtle bg-subtle text-xs uppercase text-muted">
              <tr>
                <th class="px-3 py-2 text-left font-medium">Action</th>
                <th class="px-3 py-2 text-left font-medium">Scope</th>
                <th class="px-3 py-2 text-left font-medium">Granted by</th>
                <th class="px-3 py-2 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {#each $permsQuery.data?.permissions ?? [] as p (p.id)}
                <tr class="border-b border-border-subtle last:border-b-0">
                  <td class="px-3 py-2 font-mono text-default">{p.action}</td>
                  <td class="px-3 py-2">
                    <Badge variant={p.scope === '*' ? 'default' : 'muted'}>{p.scope}</Badge>
                  </td>
                  <td class="px-3 py-2 text-xs text-muted">
                    <div>{p.granted_by}</div>
                    <div class="opacity-60">
                      {new Date(p.granted_at).toLocaleString()}
                    </div>
                  </td>
                  <td class="px-3 py-2 text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      title="Revoke"
                      disabled={$revoke.isPending}
                      onclick={() => confirmRevoke(p.id, `${p.action} @ ${p.scope}`)}
                    >
                      <Trash2 class="size-4" aria-hidden="true" />
                    </Button>
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/if}
      </div>

      <!-- Grant form -->
      <form onsubmit={submitGrant} class="space-y-3 border-t border-border-subtle pt-4">
        <p class="text-xs font-medium uppercase text-muted">Grant new permission</p>
        <label class="block text-sm">
          <span class="mb-1 block font-medium">Action</span>
          <select
            class="w-full rounded border border-border-default bg-base px-2 py-1.5 text-sm"
            bind:value={newAction}
            data-testid="perm-action"
          >
            {#each ALL_PERMISSION_ACTIONS as a (a)}
              <option value={a}>{a}</option>
            {/each}
          </select>
        </label>

        <div class="block text-sm">
          <span class="mb-1 block font-medium">Scope</span>
          <div class="flex flex-wrap gap-1" data-testid="perm-scope-chips">
            <button
              type="button"
              class={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs transition-colors ${
                wildcardSelected
                  ? 'border-accent bg-accent/10 text-accent'
                  : 'border-border-default text-muted hover:bg-subtle'
              }`}
              aria-pressed={wildcardSelected}
              onclick={toggleWildcard}
              data-testid="perm-scope-wildcard"
            >
              <Globe class="size-3" aria-hidden="true" />
              All groups (<code>*</code>)
            </button>
            {#if groups.length === 0}
              <span class="px-2 py-0.5 text-xs text-muted">
                No groups defined yet — only <code>*</code> available.
              </span>
            {:else}
              {#each groups as g (g)}
                {@const on = !wildcardSelected && selectedGroups.includes(g)}
                <button
                  type="button"
                  class={`rounded-full border px-2.5 py-0.5 font-mono text-xs transition-colors ${
                    on
                      ? 'border-accent bg-accent/10 text-accent'
                      : 'border-border-default text-muted hover:bg-subtle'
                  }`}
                  aria-pressed={on}
                  onclick={() => toggleGroup(g)}
                  data-testid={`perm-scope-${g}`}
                >
                  {g}
                </button>
              {/each}
            {/if}
          </div>
          {#if !wildcardSelected && selectedGroups.length > 1}
            <p class="mt-1 text-xs text-muted" data-testid="perm-multi-hint">
              Will create {selectedGroups.length} grants — one per group.
            </p>
          {/if}
        </div>

        <div class="flex items-center justify-between gap-2">
          <p class="text-xs text-muted">
            <code>*</code> grants on every group. Pick specific groups to scope the grant — each chip
            becomes its own row.
          </p>
          <Button type="submit" size="sm" disabled={!canSubmit} data-testid="perm-grant-submit">
            {#if $grant.isPending}
              <Loader2 class="mr-1 size-4 animate-spin" aria-hidden="true" />
            {:else}
              <Plus class="mr-1 size-4" aria-hidden="true" />
            {/if}
            Grant
            {#if !wildcardSelected && selectedGroups.length > 1}
              <span class="ml-1 font-mono text-xs">×{selectedGroups.length}</span>
            {/if}
          </Button>
        </div>
      </form>
    {/if}

    <DialogFooter>
      <Button type="button" variant="ghost" onclick={() => onOpenChange(false)}>Close</Button>
    </DialogFooter>
  </DialogContent>
</Dialog>
