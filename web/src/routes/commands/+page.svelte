<script lang="ts">
  import { Loader2, Plus, Terminal } from '@lucide/svelte';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { resolve } from '$app/paths';
  import { SvelteURLSearchParams } from 'svelte/reactivity';
  import { Button } from '$lib/components/ui/button';
  import { Card, CardContent } from '$lib/components/ui/card';
  import { Input } from '$lib/components/ui/input';
  import { cn } from '$lib/utils';
  import CommandRow from '$lib/components/app/CommandRow.svelte';
  import LiveBadge from '$lib/components/app/LiveBadge.svelte';
  import IssueCommandDialog from '$lib/components/app/IssueCommandDialog.svelte';
  import PullToRefresh from '$lib/components/app/PullToRefresh.svelte';
  import { createCommandsQuery, createHostsQuery } from '$lib/queries';
  import { runeReadable } from '$lib/queries/reactive.svelte';
  import { getLiveStream } from '$lib/queries/live-context';
  import { ALL_COMMAND_STATUSES, type CommandStatus, type CommandsQueryParams } from '$lib/api';

  const live = getLiveStream();

  // ---- Filters bound to URL ----
  const filterParams: CommandsQueryParams = $derived.by(() => {
    const sp = $page.url.searchParams;
    const statusList = sp
      .getAll('status')
      .filter((s): s is CommandStatus =>
        (ALL_COMMAND_STATUSES as ReadonlyArray<string>).includes(s),
      );
    return {
      status: statusList.length > 0 ? statusList : undefined,
      host_id: sp.get('host_id') ?? undefined,
      issued_by: sp.get('issued_by') ?? undefined,
      limit: 50,
    };
  });

  const commands = createCommandsQuery(runeReadable(() => filterParams));
  const hosts = createHostsQuery(runeReadable(() => ({})));

  const flatCommands = $derived($commands.data?.pages.flatMap((p) => p.commands) ?? []);

  let issueOpen = $state(false);
  // Mirror the URL into local state so we can debounce typing; the two
  // directions are independent, hence not a writable-derived candidate.
  // eslint-disable-next-line svelte/prefer-writable-derived
  let issuedByLocal = $state('');
  $effect(() => {
    issuedByLocal = $page.url.searchParams.get('issued_by') ?? '';
  });
  let issuedByTimer: ReturnType<typeof setTimeout> | null = null;

  function updateUrl(patch: Record<string, string | string[] | null>): void {
    const next = new SvelteURLSearchParams($page.url.searchParams);
    for (const [k, v] of Object.entries(patch)) {
      next.delete(k);
      if (Array.isArray(v)) {
        for (const item of v) next.append(k, item);
      } else if (v !== null && v !== '') {
        next.set(k, v);
      }
    }
    const qs = next.toString();
    const target = `${resolve('/commands')}${qs ? `?${qs}` : ''}` as `/${string}`;
    // eslint-disable-next-line svelte/no-navigation-without-resolve
    void goto(target, { keepFocus: true, noScroll: true, replaceState: true });
  }

  function toggleStatus(s: CommandStatus): void {
    const current = $page.url.searchParams.getAll('status');
    const next = current.includes(s) ? current.filter((x) => x !== s) : [...current, s];
    updateUrl({ status: next });
  }

  function onIssuedByInput(e: Event): void {
    issuedByLocal = (e.target as HTMLInputElement).value;
    if (issuedByTimer !== null) clearTimeout(issuedByTimer);
    issuedByTimer = setTimeout(() => updateUrl({ issued_by: issuedByLocal || null }), 250);
  }

  function clearFilters(): void {
    issuedByLocal = '';
    updateUrl({ status: [], host_id: null, issued_by: null });
  }

  const selectedStatus = $derived($page.url.searchParams.getAll('status'));
  const selectedHostId = $derived($page.url.searchParams.get('host_id') ?? '');
  const hasFilters = $derived(
    selectedStatus.length > 0 || selectedHostId !== '' || (issuedByLocal && issuedByLocal !== ''),
  );
</script>

<svelte:head>
  <title>Commands · Remote-Pulse</title>
</svelte:head>

<PullToRefresh onRefresh={() => $commands.refetch()}>
  <section class="space-y-6">
    <header class="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 class="text-2xl font-bold tracking-tight">Commands</h1>
        <p class="text-sm text-muted">Recent commands issued across the fleet, newest first.</p>
      </div>
      <div class="flex items-center gap-2">
        {#if live}
          <LiveBadge state={live.state} />
        {/if}
        <Button onclick={() => (issueOpen = true)}>
          <Plus class="size-4" aria-hidden="true" />
          New command
        </Button>
      </div>
    </header>

    <!-- Filter bar -->
    <div class="flex flex-col gap-3 rounded-lg border border-border-default bg-elevated p-3">
      <div class="flex flex-wrap items-center gap-2">
        <span class="text-xs font-medium text-muted">Status</span>
        {#each ALL_COMMAND_STATUSES as s (s)}
          {@const on = selectedStatus.includes(s)}
          <button
            type="button"
            onclick={() => toggleStatus(s)}
            class={cn(
              'touch-target inline-flex min-h-9 items-center rounded-full border px-3 py-1 text-xs font-mono transition-colors',
              on
                ? 'border-accent bg-accent-bg text-accent-text'
                : 'border-border-default text-muted hover:bg-subtle',
            )}
            aria-pressed={on}
          >
            {s}
          </button>
        {/each}
      </div>
      <div class="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <label class="block space-y-1">
          <span class="text-xs font-medium text-muted">Host</span>
          <select
            value={selectedHostId}
            onchange={(e) => updateUrl({ host_id: (e.target as HTMLSelectElement).value || null })}
            class="h-11 w-full rounded-md border border-border-default bg-base px-2 text-sm text-default focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:h-9"
          >
            <option value="">All hosts</option>
            {#each $hosts.data?.hosts ?? [] as h (h.id)}
              <option value={h.id}>{h.hostname}</option>
            {/each}
          </select>
        </label>
        <label class="block space-y-1 sm:col-span-2">
          <span class="text-xs font-medium text-muted">Issued by (email / sub)</span>
          <Input
            value={issuedByLocal}
            oninput={onIssuedByInput}
            placeholder="alice@example.com"
            aria-label="Issued by"
          />
        </label>
      </div>
      {#if hasFilters}
        <div>
          <button
            type="button"
            class="text-xs text-accent-text underline-offset-4 hover:underline"
            onclick={clearFilters}
          >
            Clear filters
          </button>
        </div>
      {/if}
    </div>

    <!-- List -->
    {#if $commands.isPending && !$commands.data}
      <div class="space-y-2" aria-busy="true">
        {#each [0, 1, 2, 3, 4] as i (i)}
          <div class="h-12 animate-pulse rounded-lg border border-border-subtle bg-subtle"></div>
        {/each}
      </div>
    {:else if $commands.isError}
      <Card>
        <CardContent class="space-y-3 py-6">
          <p class="text-sm text-muted">
            Could not load commands: {$commands.error?.message ?? 'unknown error'}.
          </p>
          <Button size="sm" onclick={() => void $commands.refetch()}>Reload</Button>
        </CardContent>
      </Card>
    {:else if flatCommands.length === 0}
      <Card>
        <CardContent class="flex flex-col items-center gap-3 py-12 text-center">
          <Terminal class="size-8 text-muted" aria-hidden="true" />
          <p class="text-sm text-muted">No commands match your filters.</p>
          <div class="flex items-center gap-2">
            {#if hasFilters}
              <Button variant="outline" size="sm" onclick={clearFilters}>Clear filters</Button>
            {/if}
            <Button size="sm" onclick={() => (issueOpen = true)}>Issue a command</Button>
          </div>
        </CardContent>
      </Card>
    {:else}
      <ul class="space-y-2">
        {#each flatCommands as cmd (cmd.id)}
          <CommandRow command={cmd} />
        {/each}
      </ul>
      {#if $commands.hasNextPage}
        <div class="flex justify-center pt-2">
          <Button
            variant="outline"
            size="sm"
            onclick={() => void $commands.fetchNextPage()}
            disabled={$commands.isFetchingNextPage}
          >
            {#if $commands.isFetchingNextPage}
              <Loader2 class="size-4 animate-spin" aria-hidden="true" />
              Loading…
            {:else}
              Load more
            {/if}
          </Button>
        </div>
      {/if}
    {/if}
  </section>
</PullToRefresh>

<IssueCommandDialog bind:open={issueOpen} onOpenChange={(v) => (issueOpen = v)} />
