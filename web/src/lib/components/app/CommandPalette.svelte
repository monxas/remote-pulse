<script lang="ts">
  import {
    Activity,
    KeyRound,
    ListTree,
    Server,
    Settings,
    ShieldAlert,
    Terminal,
  } from '@lucide/svelte';
  import { goto } from '$app/navigation';
  import { resolve } from '$app/paths';
  import {
    Command,
    CommandEmpty,
    CommandGroup,
    CommandInput,
    CommandItem,
    CommandList,
  } from '$lib/components/ui/command';
  import { Dialog, DialogContent, DialogTitle, DialogDescription } from '$lib/components/ui/dialog';
  import { createCommandsQuery, createHostsQuery, staticReadable } from '$lib/queries';
  import { runeReadable } from '$lib/queries/reactive.svelte';
  import type { HostsParams } from '$lib/queries';
  import IssueCommandDialog from './IssueCommandDialog.svelte';

  let open = $state(false);
  let issueOpen = $state(false);
  let search = $state('');

  // Only fetch the host catalogue once the palette is open — keeps the
  // initial page render hot.
  const hostsParams = runeReadable<HostsParams>(() => ({}));
  const hostsQuery = createHostsQuery(hostsParams);

  // Recent commands: pull the first page, fast-and-cheap.
  const cmdsParams = staticReadable({ limit: 20 });
  const cmdsQuery = createCommandsQuery(cmdsParams);

  const hosts = $derived($hostsQuery.data?.hosts ?? []);
  const recentCommands = $derived($cmdsQuery.data?.pages.flatMap((p) => p.commands) ?? []);

  function close(): void {
    open = false;
  }

  function go(path: string): void {
    close();
    // The `path` is always produced by `resolve()` at the call site.
    // eslint-disable-next-line svelte/no-navigation-without-resolve
    void goto(path as `/${string}`);
  }

  function isCommandKey(e: KeyboardEvent): boolean {
    return (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k';
  }

  function onKeydown(e: KeyboardEvent): void {
    if (!isCommandKey(e)) return;
    // Don't fight other modals — they sit above us in the focus stack and
    // will swallow the event before bubble. We only act on bubble.
    e.preventDefault();
    open = !open;
  }
</script>

<svelte:window onkeydown={onKeydown} />

<Dialog bind:open onOpenChange={(v) => (open = v)}>
  <DialogContent class="max-w-xl p-0 sm:p-0" showClose={false}>
    <DialogTitle class="sr-only">Command palette</DialogTitle>
    <DialogDescription class="sr-only">
      Navigate, find hosts, or jump to recent commands.
    </DialogDescription>
    <Command shouldFilter loop>
      <CommandInput bind:value={search} placeholder="Type a command or search…" />
      <CommandList>
        <CommandEmpty>No results.</CommandEmpty>

        <CommandGroup heading="Navigate">
          <CommandItem onSelect={() => go(resolve('/'))}>
            <Activity class="size-4 text-muted" aria-hidden="true" />
            Fleet
          </CommandItem>
          <CommandItem onSelect={() => go(resolve('/hosts'))}>
            <Server class="size-4 text-muted" aria-hidden="true" />
            Hosts
          </CommandItem>
          <CommandItem onSelect={() => go(resolve('/commands'))}>
            <Terminal class="size-4 text-muted" aria-hidden="true" />
            Commands
          </CommandItem>
          <CommandItem onSelect={() => go(resolve('/approvals'))}>
            <ShieldAlert class="size-4 text-muted" aria-hidden="true" />
            Approvals
          </CommandItem>
          <CommandItem onSelect={() => go(resolve('/audit'))}>
            <ListTree class="size-4 text-muted" aria-hidden="true" />
            Audit log
          </CommandItem>
          <CommandItem onSelect={() => go(resolve('/enroll'))}>
            <KeyRound class="size-4 text-muted" aria-hidden="true" />
            Enroll
          </CommandItem>
          <CommandItem onSelect={() => go(resolve('/settings'))}>
            <Settings class="size-4 text-muted" aria-hidden="true" />
            Settings
          </CommandItem>
        </CommandGroup>

        <CommandGroup heading="Actions">
          <CommandItem
            onSelect={() => {
              close();
              issueOpen = true;
            }}
            keywords={['new', 'issue', 'shell', 'reboot']}
          >
            <Terminal class="size-4 text-muted" aria-hidden="true" />
            Issue a new command…
          </CommandItem>
        </CommandGroup>

        {#if hosts.length > 0}
          <CommandGroup heading="Hosts">
            {#each hosts.slice(0, 20) as host (host.id)}
              <CommandItem
                value={`host-${host.id} ${host.hostname} ${host.group_name}`}
                keywords={[host.hostname, host.group_name]}
                onSelect={() => go(resolve('/hosts/[id]', { id: host.id }))}
              >
                <Server class="size-4 text-muted" aria-hidden="true" />
                <span class="font-mono">{host.hostname}</span>
                <span class="ml-auto text-xs text-muted">{host.group_name}</span>
              </CommandItem>
            {/each}
          </CommandGroup>
        {/if}

        {#if recentCommands.length > 0}
          <CommandGroup heading="Recent commands">
            {#each recentCommands.slice(0, 10) as cmd (cmd.id)}
              <CommandItem
                value={`cmd-${cmd.id} ${cmd.command_type} ${cmd.host_hostname}`}
                keywords={[cmd.command_type, cmd.host_hostname, cmd.status]}
                onSelect={() => go(resolve('/commands/[id]', { id: cmd.id }))}
              >
                <Terminal class="size-4 text-muted" aria-hidden="true" />
                <span class="font-mono">{cmd.command_type}</span>
                <span class="ml-auto text-xs text-muted">{cmd.host_hostname}</span>
              </CommandItem>
            {/each}
          </CommandGroup>
        {/if}
      </CommandList>
    </Command>
  </DialogContent>
</Dialog>

<IssueCommandDialog bind:open={issueOpen} onOpenChange={(v) => (issueOpen = v)} />
