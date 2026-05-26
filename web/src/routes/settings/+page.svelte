<script lang="ts">
  import {
    Key,
    Loader2,
    Plus,
    Trash2,
    Users as UsersIcon,
    FolderKanban,
    ShieldCheck,
  } from '@lucide/svelte';
  import PermissionsDialog from '$lib/components/app/PermissionsDialog.svelte';
  import SortableHeader from '$lib/components/app/SortableHeader.svelte';
  import TableSearch from '$lib/components/app/TableSearch.svelte';
  import { Badge } from '$lib/components/ui/badge';
  import { Button } from '$lib/components/ui/button';
  import { Card, CardContent, CardHeader, CardTitle } from '$lib/components/ui/card';
  import { Input } from '$lib/components/ui/input';
  import { Tabs, TabsList, TabsTrigger, TabsContent } from '$lib/components/ui/tabs';
  import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogDescription,
    DialogFooter,
  } from '$lib/components/ui/dialog';
  import {
    createSettingsGroupsQuery,
    createSettingsUsersQuery,
    createCreateGroupMutation,
    createDeleteGroupMutation,
    createCreateUserMutation,
    createUpdateUserMutation,
    createDeleteUserMutation,
  } from '$lib/queries';
  import type { SettingsGroup, SettingsUser, UserRole } from '$lib/api';
  import { createTableState } from '$lib/components/app/table-state.svelte';

  const groupsQuery = createSettingsGroupsQuery();
  const usersQuery = createSettingsUsersQuery();
  const createGroup = createCreateGroupMutation();
  const deleteGroup = createDeleteGroupMutation();
  const createUser = createCreateUserMutation();
  const updateUser = createUpdateUserMutation();
  const deleteUser = createDeleteUserMutation();

  const groups = $derived<SettingsGroup[]>($groupsQuery.data?.groups ?? []);
  const users = $derived<SettingsUser[]>($usersQuery.data?.users ?? []);
  const groupNames = $derived(groups.map((g) => g.name));

  // ---- Sort + search state for the two tables ----
  // Prefixes ('g_' for groups, 'u_' for users) namespace the URL params so
  // both tables can persist their state independently on the same route.
  const groupsTable = createTableState<SettingsGroup>(() => groups, {
    prefix: 'g_',
    searchable: ['name', 'description'],
    getSortValue: (row, key) => {
      if (key === 'host_count') return row.host_count;
      if (key === 'user_count') return row.user_count;
      return (row as unknown as Record<string, unknown>)[key];
    },
  });

  const usersTable = createTableState<SettingsUser>(() => users, {
    prefix: 'u_',
    searchable: ['email', 'name', 'role'],
    getSortValue: (row, key) => {
      if (key === 'groups') return row.groups.join(',');
      return (row as unknown as Record<string, unknown>)[key];
    },
  });

  const groupsTableDirty = $derived(
    Boolean(groupsTable.query) || groupsTable.sortKey !== null,
  );
  const usersTableDirty = $derived(
    Boolean(usersTable.query) || usersTable.sortKey !== null,
  );

  // ---- New group dialog ----
  let newGroupOpen = $state(false);
  let newGroupName = $state('');
  let newGroupDesc = $state('');

  function openNewGroup(): void {
    newGroupName = '';
    newGroupDesc = '';
    newGroupOpen = true;
  }

  function submitNewGroup(e: Event): void {
    e.preventDefault();
    const name = newGroupName.trim();
    if (!name) return;
    $createGroup.mutate(
      { name, description: newGroupDesc.trim() || null },
      {
        onSuccess: () => {
          newGroupOpen = false;
        },
      },
    );
  }

  // ---- New user dialog ----
  let newUserOpen = $state(false);
  let newUserEmail = $state('');
  let newUserName = $state('');
  let newUserRole = $state<UserRole>('viewer');
  let newUserGroups = $state<string[]>([]);

  function openNewUser(): void {
    newUserEmail = '';
    newUserName = '';
    newUserRole = 'viewer';
    newUserGroups = [];
    newUserOpen = true;
  }

  function toggleNewUserGroup(g: string): void {
    if (newUserGroups.includes(g)) {
      newUserGroups = newUserGroups.filter((x) => x !== g);
    } else {
      newUserGroups = [...newUserGroups, g];
    }
  }

  function submitNewUser(e: Event): void {
    e.preventDefault();
    const email = newUserEmail.trim();
    if (!email) return;
    $createUser.mutate(
      {
        email,
        name: newUserName.trim() || null,
        role: newUserRole,
        groups: newUserGroups,
      },
      {
        onSuccess: () => {
          newUserOpen = false;
        },
      },
    );
  }

  // ---- Inline edit user role ----
  function changeRole(user: SettingsUser, role: UserRole): void {
    if (user.role === role) return;
    $updateUser.mutate({ id: user.id, input: { role } });
  }

  function toggleUserGroup(user: SettingsUser, g: string): void {
    const next = user.groups.includes(g) ? user.groups.filter((x) => x !== g) : [...user.groups, g];
    $updateUser.mutate({ id: user.id, input: { groups: next } });
  }

  function confirmDeleteGroup(g: SettingsGroup): void {
    if (g.host_count > 0) return; // UI hint; server returns 409 anyway
    const ok = window.confirm(`Delete group "${g.name}"? This cannot be undone.`);
    if (ok) $deleteGroup.mutate(g.name);
  }

  function confirmDeleteUser(u: SettingsUser): void {
    const ok = window.confirm(`Delete user "${u.email}"? They will lose dashboard access.`);
    if (ok) $deleteUser.mutate(u.id);
  }

  // ---- Permissions modal ----
  let permsOpen = $state(false);
  let permsTarget = $state<SettingsUser | null>(null);

  function openPermissions(u: SettingsUser): void {
    permsTarget = u;
    permsOpen = true;
  }
</script>

<svelte:head>
  <title>Settings · Remote-Pulse</title>
</svelte:head>

<section class="space-y-6" data-testid="settings-page">
  <header class="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
    <div>
      <h1 class="text-2xl font-bold tracking-tight">Settings</h1>
      <p class="text-sm text-muted">
        Manage groups, dashboard users, and row-level permissions. Admin only — changes are
        captured in the audit trail.
      </p>
    </div>
    <Badge variant="default" class="self-start sm:self-end">
      <ShieldCheck class="mr-1 size-3.5" aria-hidden="true" />
      admin required
    </Badge>
  </header>

  <Tabs value="groups" class="space-y-4">
    <TabsList>
      <TabsTrigger value="groups" data-testid="tab-groups">
        <FolderKanban class="mr-1.5 size-4" aria-hidden="true" />
        Groups
        <Badge variant="muted" class="ml-2">{groups.length}</Badge>
      </TabsTrigger>
      <TabsTrigger value="users" data-testid="tab-users">
        <UsersIcon class="mr-1.5 size-4" aria-hidden="true" />
        Users
        <Badge variant="muted" class="ml-2">{users.length}</Badge>
      </TabsTrigger>
    </TabsList>

    <!-- ====================== GROUPS TAB ====================== -->
    <TabsContent value="groups" class="space-y-4">
      <div class="flex items-center justify-end">
        <Button size="sm" onclick={openNewGroup} data-testid="new-group-btn">
          <Plus class="mr-1 size-4" aria-hidden="true" />
          New group
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle class="text-base">Groups</CardTitle>
        </CardHeader>
        <CardContent class="p-0">
          {#if $groupsQuery.isPending}
            <div class="flex items-center gap-2 px-4 py-8 text-sm text-muted">
              <Loader2 class="size-4 animate-spin" aria-hidden="true" />
              Loading groups…
            </div>
          {:else if $groupsQuery.isError}
            <div class="space-y-2 px-4 py-6 text-sm">
              <p class="text-danger-text">
                Failed to load groups: {$groupsQuery.error?.message ?? 'unknown error'}
              </p>
              <Button size="sm" onclick={() => void $groupsQuery.refetch()}>Retry</Button>
            </div>
          {:else if groups.length === 0}
            <div class="px-4 py-8 text-center text-sm text-muted">
              No groups yet. Create one to organise hosts and grant access.
            </div>
          {:else}
            <div class="border-b border-border-subtle px-4 py-3">
              <TableSearch
                value={groupsTable.query}
                onChange={(q) => groupsTable.setQuery(q)}
                onReset={() => groupsTable.reset()}
                showReset={groupsTableDirty}
                placeholder="Search by name or description…"
                label="Search groups"
                testId="groups-search"
              />
            </div>
            <div class="overflow-x-auto">
              <table class="w-full text-sm" data-testid="groups-table">
                <thead class="border-b border-border-subtle bg-subtle text-xs uppercase text-muted">
                  <tr>
                    <SortableHeader
                      columnKey="name"
                      activeKey={groupsTable.sortKey}
                      activeDir={groupsTable.sortDir}
                      onToggle={(k) => groupsTable.toggleSort(k)}
                    >
                      Name
                    </SortableHeader>
                    <SortableHeader
                      columnKey="description"
                      activeKey={groupsTable.sortKey}
                      activeDir={groupsTable.sortDir}
                      onToggle={(k) => groupsTable.toggleSort(k)}
                    >
                      Description
                    </SortableHeader>
                    <SortableHeader
                      columnKey="host_count"
                      activeKey={groupsTable.sortKey}
                      activeDir={groupsTable.sortDir}
                      onToggle={(k) => groupsTable.toggleSort(k)}
                      align="right"
                    >
                      Hosts
                    </SortableHeader>
                    <SortableHeader
                      columnKey="user_count"
                      activeKey={groupsTable.sortKey}
                      activeDir={groupsTable.sortDir}
                      onToggle={(k) => groupsTable.toggleSort(k)}
                      align="right"
                    >
                      Users
                    </SortableHeader>
                    <th scope="col" class="px-4 py-2 text-right font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {#if groupsTable.view.length === 0}
                    <tr>
                      <td colspan="5" class="px-4 py-6 text-center text-sm text-muted">
                        No groups match “{groupsTable.query}”.
                      </td>
                    </tr>
                  {:else}
                    {#each groupsTable.view as g (g.name)}
                      <tr class="border-b border-border-subtle last:border-b-0">
                        <td class="px-4 py-2 font-mono text-default">{g.name}</td>
                        <td class="px-4 py-2 text-muted">{g.description ?? '—'}</td>
                        <td class="px-4 py-2 text-right tabular-nums">{g.host_count}</td>
                        <td class="px-4 py-2 text-right tabular-nums">{g.user_count}</td>
                        <td class="px-4 py-2 text-right">
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={g.host_count > 0 || $deleteGroup.isPending}
                            title={g.host_count > 0
                              ? 'Reassign hosts before deleting'
                              : 'Delete group'}
                            onclick={() => confirmDeleteGroup(g)}
                          >
                            <Trash2 class="size-4" aria-hidden="true" />
                          </Button>
                        </td>
                      </tr>
                    {/each}
                  {/if}
                </tbody>
              </table>
            </div>
          {/if}
        </CardContent>
      </Card>
    </TabsContent>

    <!-- ====================== USERS TAB ====================== -->
    <TabsContent value="users" class="space-y-4">
      <div class="flex items-center justify-end">
        <Button size="sm" onclick={openNewUser} data-testid="new-user-btn">
          <Plus class="mr-1 size-4" aria-hidden="true" />
          Invite user
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle class="text-base">Users</CardTitle>
        </CardHeader>
        <CardContent class="p-0">
          {#if $usersQuery.isPending}
            <div class="flex items-center gap-2 px-4 py-8 text-sm text-muted">
              <Loader2 class="size-4 animate-spin" aria-hidden="true" />
              Loading users…
            </div>
          {:else if $usersQuery.isError}
            <div class="space-y-2 px-4 py-6 text-sm">
              <p class="text-danger-text">
                Failed to load users: {$usersQuery.error?.message ?? 'unknown error'}
              </p>
              <Button size="sm" onclick={() => void $usersQuery.refetch()}>Retry</Button>
            </div>
          {:else if users.length === 0}
            <div class="px-4 py-8 text-center text-sm text-muted">No users yet.</div>
          {:else}
            <div class="border-b border-border-subtle px-4 py-3">
              <TableSearch
                value={usersTable.query}
                onChange={(q) => usersTable.setQuery(q)}
                onReset={() => usersTable.reset()}
                showReset={usersTableDirty}
                placeholder="Search by email, name or role…"
                label="Search users"
                testId="users-search"
              />
            </div>
            <div class="overflow-x-auto">
              <table class="w-full text-sm" data-testid="users-table">
                <thead class="border-b border-border-subtle bg-subtle text-xs uppercase text-muted">
                  <tr>
                    <SortableHeader
                      columnKey="email"
                      activeKey={usersTable.sortKey}
                      activeDir={usersTable.sortDir}
                      onToggle={(k) => usersTable.toggleSort(k)}
                    >
                      Email
                    </SortableHeader>
                    <SortableHeader
                      columnKey="role"
                      activeKey={usersTable.sortKey}
                      activeDir={usersTable.sortDir}
                      onToggle={(k) => usersTable.toggleSort(k)}
                    >
                      Role
                    </SortableHeader>
                    <SortableHeader
                      columnKey="groups"
                      activeKey={usersTable.sortKey}
                      activeDir={usersTable.sortDir}
                      onToggle={(k) => usersTable.toggleSort(k)}
                    >
                      Groups
                    </SortableHeader>
                    <th scope="col" class="px-4 py-2 text-right font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {#if usersTable.view.length === 0}
                    <tr>
                      <td colspan="4" class="px-4 py-6 text-center text-sm text-muted">
                        No users match “{usersTable.query}”.
                      </td>
                    </tr>
                  {:else}
                    {#each usersTable.view as u (u.id)}
                    <tr class="border-b border-border-subtle last:border-b-0">
                      <td class="px-4 py-2">
                        <div class="font-medium text-default">{u.email}</div>
                        {#if u.name}
                          <div class="text-xs text-muted">{u.name}</div>
                        {/if}
                        {#if !u.is_active}
                          <Badge variant="muted" class="mt-1">disabled</Badge>
                        {/if}
                      </td>
                      <td class="px-4 py-2">
                        <select
                          class="rounded border border-border-default bg-base px-2 py-1 text-xs"
                          value={u.role}
                          onchange={(e) =>
                            changeRole(u, (e.currentTarget as HTMLSelectElement).value as UserRole)}
                          disabled={$updateUser.isPending}
                          aria-label={`Role for ${u.email}`}
                        >
                          <option value="admin">admin</option>
                          <option value="operator">operator</option>
                          <option value="viewer">viewer</option>
                        </select>
                      </td>
                      <td class="px-4 py-2">
                        <div class="flex flex-wrap gap-1">
                          {#if groupNames.length === 0}
                            <span class="text-xs text-muted">No groups available</span>
                          {:else}
                            {#each groupNames as g (g)}
                              {@const on = u.groups.includes(g)}
                              <button
                                type="button"
                                class={`rounded-full border px-2 py-0.5 text-xs transition-colors ${
                                  on
                                    ? 'border-accent bg-accent/10 text-accent'
                                    : 'border-border-default text-muted hover:bg-subtle'
                                }`}
                                onclick={() => toggleUserGroup(u, g)}
                                disabled={$updateUser.isPending}
                              >
                                {g}
                              </button>
                            {/each}
                          {/if}
                        </div>
                      </td>
                      <td class="px-4 py-2 text-right">
                        <Button
                          variant="ghost"
                          size="sm"
                          onclick={() => openPermissions(u)}
                          title="Manage row-level permissions"
                          data-testid="perms-btn"
                        >
                          <Key class="size-4" aria-hidden="true" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onclick={() => confirmDeleteUser(u)}
                          disabled={$deleteUser.isPending}
                          title="Delete user"
                        >
                          <Trash2 class="size-4" aria-hidden="true" />
                        </Button>
                      </td>
                    </tr>
                    {/each}
                  {/if}
                </tbody>
              </table>
            </div>
          {/if}
        </CardContent>
      </Card>
    </TabsContent>
  </Tabs>
</section>

<!-- ====================== Dialog: New group ====================== -->
<Dialog bind:open={newGroupOpen} onOpenChange={(o) => (newGroupOpen = o)}>
  <DialogContent>
    <form onsubmit={submitNewGroup}>
      <DialogHeader>
        <DialogTitle>Create group</DialogTitle>
        <DialogDescription>
          Groups bucket hosts and gate dashboard access. Name must be DNS-safe (a-z, 0-9, _, -, .).
        </DialogDescription>
      </DialogHeader>
      <div class="space-y-3 py-4">
        <label class="block text-sm">
          <span class="mb-1 block font-medium">Name</span>
          <Input bind:value={newGroupName} placeholder="prod" required />
        </label>
        <label class="block text-sm">
          <span class="mb-1 block font-medium">Description</span>
          <Input bind:value={newGroupDesc} placeholder="Production fleet" />
        </label>
      </div>
      <DialogFooter>
        <Button type="button" variant="ghost" onclick={() => (newGroupOpen = false)}>Cancel</Button>
        <Button type="submit" disabled={$createGroup.isPending || !newGroupName.trim()}>
          {#if $createGroup.isPending}
            <Loader2 class="mr-1 size-4 animate-spin" aria-hidden="true" />
          {/if}
          Create
        </Button>
      </DialogFooter>
    </form>
  </DialogContent>
</Dialog>

<!-- ====================== Dialog: Permissions ====================== -->
<PermissionsDialog
  bind:open={permsOpen}
  onOpenChange={(o) => (permsOpen = o)}
  user={permsTarget}
  groups={groupNames}
/>

<!-- ====================== Dialog: New user ====================== -->
<Dialog bind:open={newUserOpen} onOpenChange={(o) => (newUserOpen = o)}>
  <DialogContent>
    <form onsubmit={submitNewUser}>
      <DialogHeader>
        <DialogTitle>Invite user</DialogTitle>
        <DialogDescription>
          The user can log in via PocketID using the email below. Their real OIDC sub binds on first
          login.
        </DialogDescription>
      </DialogHeader>
      <div class="space-y-3 py-4">
        <label class="block text-sm">
          <span class="mb-1 block font-medium">Email</span>
          <Input bind:value={newUserEmail} type="email" placeholder="user@example.com" required />
        </label>
        <label class="block text-sm">
          <span class="mb-1 block font-medium">Name</span>
          <Input bind:value={newUserName} placeholder="optional" />
        </label>
        <label class="block text-sm">
          <span class="mb-1 block font-medium">Role</span>
          <select
            class="w-full rounded border border-border-default bg-base px-2 py-1.5 text-sm"
            bind:value={newUserRole}
          >
            <option value="viewer">viewer — read-only</option>
            <option value="operator">operator — can issue commands</option>
            <option value="admin">admin — full settings access</option>
          </select>
        </label>
        <div class="block text-sm">
          <span class="mb-1 block font-medium">Groups</span>
          <div class="flex flex-wrap gap-1">
            {#if groupNames.length === 0}
              <span class="text-xs text-muted">Create a group first.</span>
            {:else}
              {#each groupNames as g (g)}
                {@const on = newUserGroups.includes(g)}
                <button
                  type="button"
                  class={`rounded-full border px-2 py-0.5 text-xs transition-colors ${
                    on
                      ? 'border-accent bg-accent/10 text-accent'
                      : 'border-border-default text-muted hover:bg-subtle'
                  }`}
                  onclick={() => toggleNewUserGroup(g)}
                >
                  {g}
                </button>
              {/each}
            {/if}
          </div>
        </div>
      </div>
      <DialogFooter>
        <Button type="button" variant="ghost" onclick={() => (newUserOpen = false)}>Cancel</Button>
        <Button type="submit" disabled={$createUser.isPending || !newUserEmail.trim()}>
          {#if $createUser.isPending}
            <Loader2 class="mr-1 size-4 animate-spin" aria-hidden="true" />
          {/if}
          Invite
        </Button>
      </DialogFooter>
    </form>
  </DialogContent>
</Dialog>
