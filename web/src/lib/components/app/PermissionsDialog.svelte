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
  import { Loader2, Plus, ShieldCheck, Trash2, Key } from '@lucide/svelte';
  import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogDescription,
    DialogFooter,
  } from '$lib/components/ui/dialog';
  import { Button } from '$lib/components/ui/button';
  import { Input } from '$lib/components/ui/input';
  import { Badge } from '$lib/components/ui/badge';
  import {
    createGrantPermissionMutation,
    createRevokePermissionMutation,
    createUserPermissionsQuery,
  } from '$lib/queries';
  import { runeReadable } from '$lib/queries/reactive.svelte';
  import { userStore } from '$lib/stores/user.svelte';
  import {
    ALL_PERMISSION_ACTIONS,
    type PermissionAction,
    type SettingsUser,
  } from '$lib/api';

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
  let newAction = $state<PermissionAction>('command.issue');
  let newScope = $state<string>('*');

  $effect(() => {
    // Reset the form whenever the dialog opens against a fresh user so the
    // last selection doesn't leak between modals.
    if (open && user) {
      newAction = 'command.issue';
      newScope = '*';
    }
  });

  const isAdmin = $derived(user?.role === 'admin');

  function submitGrant(e: Event): void {
    e.preventDefault();
    if (!user) return;
    const scope = newScope.trim() || '*';
    $grant.mutate({
      userId: user.id,
      input: { action: newAction, scope },
    });
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
          Fine-grained ACL for <span class="font-mono">{user.email}</span>. These rows layer on
          top of role + accessible groups.
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
            This user is an <strong>admin</strong> and implicitly holds every action. Explicit
            grants below are honoured but redundant.
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
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_1fr_auto]">
          <label class="block text-sm">
            <span class="mb-1 block font-medium">Action</span>
            <select
              class="w-full rounded border border-border-default bg-base px-2 py-1.5 text-sm"
              bind:value={newAction}
            >
              {#each ALL_PERMISSION_ACTIONS as a (a)}
                <option value={a}>{a}</option>
              {/each}
            </select>
          </label>
          <label class="block text-sm">
            <span class="mb-1 block font-medium">Scope</span>
            <Input
              bind:value={newScope}
              placeholder="* or group name"
              list="permission-scope-suggestions"
            />
            <datalist id="permission-scope-suggestions">
              <option value="*"></option>
              {#each groups as g (g)}
                <option value={g}></option>
              {/each}
            </datalist>
          </label>
          <div class="flex items-end">
            <Button type="submit" size="sm" disabled={$grant.isPending}>
              {#if $grant.isPending}
                <Loader2 class="mr-1 size-4 animate-spin" aria-hidden="true" />
              {:else}
                <Plus class="mr-1 size-4" aria-hidden="true" />
              {/if}
              Grant
            </Button>
          </div>
        </div>
        <p class="text-xs text-muted">
          Scope <code>*</code> grants the action on every group. Otherwise, the row matches only
          hosts whose <code>group_name</code> equals the scope string.
        </p>
      </form>
    {/if}

    <DialogFooter>
      <Button type="button" variant="ghost" onclick={() => onOpenChange(false)}>Close</Button>
    </DialogFooter>
  </DialogContent>
</Dialog>
