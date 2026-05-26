<script lang="ts" module>
  /**
   * Public mode enum exported from the module scope so consumers can
   * import the type without re-declaring it.
   */
  export type BulkMode = 'role' | 'add-group' | 'remove-group' | 'grant' | 'delete' | null;
</script>

<script lang="ts">
  import { Loader2, AlertTriangle } from '@lucide/svelte';
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
  import { toast } from 'svelte-sonner';
  import { useQueryClient } from '@tanstack/svelte-query';
  import {
    ALL_PERMISSION_ACTIONS,
    type PermissionAction,
    type SettingsUser,
    type UserRole,
  } from '$lib/api';
  import {
    bulkChangeRole,
    bulkAddUsersToGroup,
    bulkRemoveUsersFromGroup,
    bulkGrantPermission,
    bulkDeleteUsers,
    type BulkUserItem,
  } from '$lib/settings/bulk-user-ops';
  import { qk } from '$lib/queries';

  /**
   * Wraps the five bulk-user modals (role / add-group / remove-group /
   * grant / delete) in a single component so the Settings page only
   * needs to track `mode` + `open` instead of five flags. Each modal
   * shares the same submit-with-progress UX and re-uses the toast
   * conventions established by v1.0.9 bulk-command.
   *
   * Safety net: the parent passes `currentUserId` so we can always
   * surface a confirmation when the bulk delete includes the signed-in
   * admin (we don't auto-strip — we just refuse and ask the user to
   * deselect themselves). Self-demote is handled the same way.
   */

  type Props = {
    mode: BulkMode;
    open: boolean;
    onOpenChange: (next: boolean) => void;
    users: ReadonlyArray<SettingsUser>;
    groups: ReadonlyArray<string>;
    currentUserId: string | null;
    onSettled: () => void;
  };

  let { mode, open, onOpenChange, users, groups, currentUserId, onSettled }: Props = $props();

  // ---- Shared submit state ----
  let inFlight = $state(false);
  let progress = $state<BulkUserItem[]>([]);

  // ---- Form state per mode ----
  let role = $state<UserRole>('viewer');
  let pickedGroup = $state<string>('');
  let grantAction = $state<PermissionAction>('command.issue');
  let grantScope = $state<string>('*');
  let deleteConfirm = $state<string>('');

  // ---- Reset every time the dialog opens against a fresh mode ----
  $effect(() => {
    if (open) {
      progress = [];
      inFlight = false;
      role = 'viewer';
      pickedGroup = groups[0] ?? '';
      grantAction = 'command.issue';
      grantScope = '*';
      deleteConfirm = '';
    }
  });

  // ---- Derived guardrails ----

  /** The signed-in admin appears in the selection — we refuse self-* ops. */
  const selfInSelection = $derived(!!currentUserId && users.some((u) => u.id === currentUserId));

  /** Bulk delete: surface the admin count + flag full-admin wipeouts. */
  const adminCount = $derived(users.filter((u) => u.role === 'admin').length);
  const allSelectedAreAdmins = $derived(users.length > 0 && adminCount === users.length);

  /** Set of group names every selected user has in common (for remove-group). */
  const commonGroups = $derived.by<string[]>(() => {
    if (users.length === 0) return [];
    const [first, ...rest] = users;
    return first!.groups.filter((g) => rest.every((u) => u.groups.includes(g)));
  });

  // High-friction confirmation phrase for bulk delete.
  const DELETE_PHRASE = 'DELETE';

  const client = useQueryClient();

  function close(): void {
    if (inFlight) return;
    onOpenChange(false);
  }

  function emit(item: BulkUserItem): void {
    // Replace the per-user row in place. We sort visually by email in
    // the parent table so insertion order doesn't matter here.
    const idx = progress.findIndex((p) => p.user_id === item.user_id);
    if (idx === -1) progress = [...progress, item];
    else {
      const next = [...progress];
      next[idx] = item;
      progress = next;
    }
  }

  function summarize(label: string, ok: number, err: number): void {
    if (err === 0) toast.success(`${ok} ${label}`);
    else if (ok === 0) toast.error(`${err} failed`);
    else toast.warning(`${ok} ${label}, ${err} failed`);
  }

  async function submit(): Promise<void> {
    if (inFlight || users.length === 0 || !mode) return;
    inFlight = true;
    try {
      if (mode === 'role') {
        // Block self-demote to viewer (admin demoting themselves locks them out).
        if (
          selfInSelection &&
          role === 'viewer' &&
          users.find((u) => u.id === currentUserId)?.role === 'admin'
        ) {
          toast.error('Cannot demote yourself from admin to viewer.');
          inFlight = false;
          return;
        }
        const { okCount, errorCount } = await bulkChangeRole(users, role, emit);
        summarize(`role${okCount === 1 ? '' : 's'} updated`, okCount, errorCount);
      } else if (mode === 'add-group') {
        if (!pickedGroup) {
          toast.error('Pick a group.');
          inFlight = false;
          return;
        }
        const { okCount, errorCount } = await bulkAddUsersToGroup(users, pickedGroup, emit);
        summarize(`user${okCount === 1 ? '' : 's'} added to ${pickedGroup}`, okCount, errorCount);
      } else if (mode === 'remove-group') {
        if (!pickedGroup) {
          toast.error('Pick a group.');
          inFlight = false;
          return;
        }
        const { okCount, errorCount } = await bulkRemoveUsersFromGroup(users, pickedGroup, emit);
        summarize(
          `user${okCount === 1 ? '' : 's'} removed from ${pickedGroup}`,
          okCount,
          errorCount,
        );
      } else if (mode === 'grant') {
        const scope = grantScope.trim() || '*';
        const { okCount, errorCount } = await bulkGrantPermission(
          users,
          { action: grantAction, scope },
          emit,
        );
        summarize(`grant${okCount === 1 ? '' : 's'} applied`, okCount, errorCount);
      } else if (mode === 'delete') {
        if (selfInSelection) {
          toast.error('Deselect your own account before bulk delete.');
          inFlight = false;
          return;
        }
        if (deleteConfirm !== DELETE_PHRASE) {
          toast.error(`Type ${DELETE_PHRASE} to confirm.`);
          inFlight = false;
          return;
        }
        const { okCount, errorCount } = await bulkDeleteUsers(users, emit);
        summarize(`user${okCount === 1 ? '' : 's'} deleted`, okCount, errorCount);
      }

      // Invalidate everything so the table re-fetches with the new state.
      void client.invalidateQueries({ queryKey: qk.settingsAll() });
      onSettled();
      onOpenChange(false);
    } finally {
      inFlight = false;
    }
  }

  const title = $derived(
    mode === 'role'
      ? 'Change role'
      : mode === 'add-group'
        ? 'Add to group'
        : mode === 'remove-group'
          ? 'Remove from group'
          : mode === 'grant'
            ? 'Grant permission'
            : mode === 'delete'
              ? 'Delete users'
              : '',
  );
</script>

<Dialog bind:open onOpenChange={(o) => onOpenChange(o)}>
  <DialogContent class="max-w-xl">
    <DialogHeader>
      <DialogTitle>
        {#if mode === 'delete'}
          <AlertTriangle class="mr-1 inline size-4 text-danger-text" aria-hidden="true" />
        {/if}
        {title}
      </DialogTitle>
      <DialogDescription>
        Action will affect <strong>{users.length}</strong>
        user{users.length === 1 ? '' : 's'}. Each row dispatches its own request.
      </DialogDescription>
    </DialogHeader>

    <!-- Selection preview (always shown so the user can sanity-check) -->
    <div class="max-h-32 overflow-y-auto rounded-md border border-border-subtle bg-subtle p-2">
      <ul class="space-y-1 text-xs" data-testid="bulk-user-targets">
        {#each users as u (u.id)}
          <li class="flex items-center justify-between gap-2">
            <span class="font-mono">{u.email}</span>
            <div class="flex items-center gap-1">
              <Badge variant="muted">{u.role}</Badge>
              {#if u.id === currentUserId}
                <Badge variant="default">you</Badge>
              {/if}
            </div>
          </li>
        {/each}
      </ul>
    </div>

    <!-- Per-mode body -->
    {#if mode === 'role'}
      <label class="block text-sm">
        <span class="mb-1 block font-medium">New role</span>
        <select
          class="w-full rounded border border-border-default bg-base px-2 py-1.5 text-sm"
          bind:value={role}
          data-testid="bulk-role-select"
        >
          <option value="viewer">viewer — read-only</option>
          <option value="operator">operator — can issue commands</option>
          <option value="admin">admin — full settings access</option>
        </select>
      </label>
      {#if selfInSelection && role === 'viewer' && users.find((u) => u.id === currentUserId)?.role === 'admin'}
        <p class="rounded-md border border-border-default bg-warn-bg p-2 text-xs text-warn-text">
          Refusing self-demote: your own admin row is in the selection.
        </p>
      {/if}
    {:else if mode === 'add-group' || mode === 'remove-group'}
      <label class="block text-sm">
        <span class="mb-1 block font-medium">Group</span>
        <select
          class="w-full rounded border border-border-default bg-base px-2 py-1.5 text-sm"
          bind:value={pickedGroup}
          data-testid="bulk-group-select"
        >
          {#if mode === 'remove-group'}
            {#each commonGroups as g (g)}
              <option value={g}>{g}</option>
            {/each}
            {#if commonGroups.length === 0}
              <option value="" disabled>No group is shared by every selected user.</option>
            {/if}
          {:else}
            {#each groups as g (g)}
              <option value={g}>{g}</option>
            {/each}
          {/if}
        </select>
      </label>
    {:else if mode === 'grant'}
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label class="block text-sm">
          <span class="mb-1 block font-medium">Action</span>
          <select
            class="w-full rounded border border-border-default bg-base px-2 py-1.5 text-sm"
            bind:value={grantAction}
            data-testid="bulk-grant-action"
          >
            {#each ALL_PERMISSION_ACTIONS as a (a)}
              <option value={a}>{a}</option>
            {/each}
          </select>
        </label>
        <label class="block text-sm">
          <span class="mb-1 block font-medium">Scope</span>
          <Input
            bind:value={grantScope}
            placeholder="* or group name"
            data-testid="bulk-grant-scope"
            list="bulk-grant-scope-suggestions"
          />
          <datalist id="bulk-grant-scope-suggestions">
            <option value="*"></option>
            {#each groups as g (g)}
              <option value={g}></option>
            {/each}
          </datalist>
        </label>
      </div>
      <p class="text-xs text-muted">
        Grants <code>{grantAction}</code> on <code>{grantScope || '*'}</code> for every selected user.
      </p>
    {:else if mode === 'delete'}
      {#if selfInSelection}
        <p
          class="rounded-md border border-border-default bg-danger-bg p-2 text-xs text-danger-text"
          data-testid="bulk-delete-self-warning"
        >
          Your own account is in the selection. Deselect yourself before deleting.
        </p>
      {:else}
        {#if allSelectedAreAdmins}
          <p
            class="rounded-md border border-border-default bg-warn-bg p-2 text-xs text-warn-text"
            data-testid="bulk-delete-all-admins-warning"
          >
            All {users.length} selected accounts are admins. Deleting them all locks the dashboard out
            of admin recovery.
          </p>
        {/if}
        <label class="block text-sm">
          <span class="mb-1 block font-medium">
            Type <code>{DELETE_PHRASE}</code> to confirm
          </span>
          <Input
            bind:value={deleteConfirm}
            placeholder={DELETE_PHRASE}
            data-testid="bulk-delete-confirm"
            autocomplete="off"
          />
        </label>
      {/if}
    {/if}

    <!-- Progress strip while we fire ----------------------------------- -->
    {#if progress.length > 0}
      <div class="space-y-1 rounded-md border border-border-subtle p-2 text-xs">
        {#each progress as p (p.user_id)}
          <div
            class="flex items-center justify-between gap-2"
            data-testid={`bulk-user-progress-${p.email}`}
            data-status={p.status}
          >
            <span class="font-mono">{p.email}</span>
            <span class="flex items-center gap-1">
              {#if p.status === 'in-flight'}
                <Loader2 class="size-3 animate-spin" aria-hidden="true" />
                <span class="text-muted">in flight</span>
              {:else if p.status === 'success'}
                <Badge variant="success">ok</Badge>
              {:else if p.status === 'error'}
                <Badge variant="danger">{p.httpStatus ?? 'err'}</Badge>
                <span class="text-danger-text">{p.error}</span>
              {/if}
            </span>
          </div>
        {/each}
      </div>
    {/if}

    <DialogFooter>
      <Button type="button" variant="ghost" onclick={close} disabled={inFlight}>Cancel</Button>
      <Button
        type="button"
        variant={mode === 'delete' ? 'danger' : 'default'}
        onclick={submit}
        disabled={inFlight ||
          users.length === 0 ||
          (mode === 'remove-group' && commonGroups.length === 0) ||
          (mode === 'add-group' && groups.length === 0) ||
          (mode === 'delete' && (selfInSelection || deleteConfirm !== DELETE_PHRASE))}
        data-testid="bulk-user-submit"
      >
        {#if inFlight}
          <Loader2 class="mr-1 size-4 animate-spin" aria-hidden="true" />
        {/if}
        {mode === 'delete' ? 'Delete' : 'Apply'}
      </Button>
    </DialogFooter>
  </DialogContent>
</Dialog>
