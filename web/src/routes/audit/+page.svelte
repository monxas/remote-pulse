<script lang="ts">
  import { Loader2, ListTree, Download, ChevronDown } from '@lucide/svelte';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { resolve } from '$app/paths';
  import { SvelteURLSearchParams } from 'svelte/reactivity';
  import { Button } from '$lib/components/ui/button';
  import { Card, CardContent } from '$lib/components/ui/card';
  import { Input } from '$lib/components/ui/input';
  import { cn } from '$lib/utils';
  import LiveBadge from '$lib/components/app/LiveBadge.svelte';
  import AuditEvent from '$lib/components/app/AuditEvent.svelte';
  import PullToRefresh from '$lib/components/app/PullToRefresh.svelte';
  import { createAuditQuery } from '$lib/queries';
  import { runeReadable } from '$lib/queries/reactive.svelte';
  import { getLiveStream } from '$lib/queries/live-context';
  import {
    ALL_AUDIT_ACTIONS,
    buildAuditExportUrl,
    type AuditAction,
    type AuditQueryParams,
    type AuditTargetType,
  } from '$lib/api';
  import { CLEAR_FILTERS_PATCH, RANGES, paramsFromSearch, type Range } from './audit-filters';

  const live = getLiveStream();

  const params: AuditQueryParams = $derived(paramsFromSearch($page.url.searchParams));

  const audit = createAuditQuery(runeReadable(() => params));
  const events = $derived($audit.data?.pages.flatMap((p) => p.events) ?? []);
  // ``total`` is consistent across pages (per server contract); use the
  // first page's count so the displayed total doesn't bounce as the user
  // pages.
  const total = $derived($audit.data?.pages[0]?.total ?? 0);

  // Mirror the URL into local state so we can debounce typing; the two
  // directions are independent, hence not a writable-derived candidate.
  // eslint-disable-next-line svelte/prefer-writable-derived
  let actorLocal = $state('');
  $effect(() => {
    actorLocal = $page.url.searchParams.get('actor') ?? '';
  });
  let actorTimer: ReturnType<typeof setTimeout> | null = null;

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
    const target = `${resolve('/audit')}${qs ? `?${qs}` : ''}` as `/${string}`;
    // eslint-disable-next-line svelte/no-navigation-without-resolve
    void goto(target, { keepFocus: true, noScroll: true, replaceState: true });
  }

  function toggleAction(a: AuditAction): void {
    const current = $page.url.searchParams.getAll('action');
    const next = current.includes(a) ? current.filter((x) => x !== a) : [...current, a];
    updateUrl({ action: next });
  }

  function onActorInput(e: Event): void {
    actorLocal = (e.target as HTMLInputElement).value;
    if (actorTimer !== null) clearTimeout(actorTimer);
    actorTimer = setTimeout(() => updateUrl({ actor: actorLocal || null }), 250);
  }

  const selectedActions = $derived($page.url.searchParams.getAll('action'));
  const selectedTarget = $derived($page.url.searchParams.get('target_type') ?? '');
  const range = $derived(($page.url.searchParams.get('range') ?? '7d') as Range);
  const since = $derived($page.url.searchParams.get('since') ?? '');
  const until = $derived($page.url.searchParams.get('until') ?? '');

  // Mirror action_prefix into local state so we can debounce typing.
  // eslint-disable-next-line svelte/prefer-writable-derived
  let actionPrefixLocal = $state('');
  $effect(() => {
    actionPrefixLocal = $page.url.searchParams.get('action_prefix') ?? '';
  });
  let actionPrefixTimer: ReturnType<typeof setTimeout> | null = null;
  function onActionPrefixInput(e: Event): void {
    actionPrefixLocal = (e.target as HTMLInputElement).value;
    if (actionPrefixTimer !== null) clearTimeout(actionPrefixTimer);
    actionPrefixTimer = setTimeout(
      () => updateUrl({ action_prefix: actionPrefixLocal || null }),
      250,
    );
  }

  const ranges = RANGES;

  const targetTypes: ReadonlyArray<{ value: AuditTargetType | ''; label: string }> = [
    { value: '', label: 'Any target' },
    { value: 'command', label: 'Command' },
    { value: 'host', label: 'Host' },
    { value: 'enrollment', label: 'Enrollment' },
    { value: 'user', label: 'User' },
    { value: 'group', label: 'Group' },
  ];

  function clearFilters(): void {
    actorLocal = '';
    actionPrefixLocal = '';
    updateUrl(CLEAR_FILTERS_PATCH);
  }

  // Export dropdown — admin-only on the backend; non-admins will see 403 in
  // the toast. We keep the UI uniform so admins on shared dashboards don't
  // have to refresh after a role change.
  let exportOpen = $state(false);

  function exportHref(format: 'csv' | 'json'): string {
    return buildAuditExportUrl(params, format);
  }
</script>

<svelte:head>
  <title>Audit · Remote-Pulse</title>
</svelte:head>

<PullToRefresh onRefresh={() => $audit.refetch()}>
<section class="space-y-6">
  <header class="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
    <div>
      <h1 class="text-2xl font-bold tracking-tight">Audit log</h1>
      <p class="text-sm text-muted">Every state-changing event in the system, append-only.</p>
    </div>
    <div class="flex items-center gap-2">
      {#if live}
        <LiveBadge state={live.state} />
      {/if}
      <div class="relative">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onclick={() => (exportOpen = !exportOpen)}
          aria-haspopup="menu"
          aria-expanded={exportOpen}
          data-testid="audit-export-button"
        >
          <Download class="size-4" aria-hidden="true" />
          Export
          <ChevronDown class="size-3.5" aria-hidden="true" />
        </Button>
        {#if exportOpen}
          <!-- Click-away handler closes the menu when interacting elsewhere. -->
          <button
            type="button"
            class="fixed inset-0 z-10 cursor-default"
            aria-hidden="true"
            tabindex="-1"
            onclick={() => (exportOpen = false)}
          ></button>
          <div
            role="menu"
            class="absolute right-0 z-20 mt-1 w-40 overflow-hidden rounded-md border border-border-default bg-elevated shadow-lg"
          >
            <!-- The href targets the backend export endpoint directly (out of SvelteKit's router). -->
            <!-- eslint-disable svelte/no-navigation-without-resolve -->
            <a
              role="menuitem"
              href={exportHref('csv')}
              download
              data-testid="audit-export-csv"
              class="block px-3 py-2 text-sm hover:bg-subtle"
              onclick={() => (exportOpen = false)}
            >
              Export as CSV
            </a>
            <a
              role="menuitem"
              href={exportHref('json')}
              download
              data-testid="audit-export-json"
              class="block px-3 py-2 text-sm hover:bg-subtle"
              onclick={() => (exportOpen = false)}
            >
              Export as JSON
            </a>
            <!-- eslint-enable svelte/no-navigation-without-resolve -->
          </div>
        {/if}
      </div>
    </div>
  </header>

  <div class="space-y-3 rounded-lg border border-border-default bg-elevated p-3">
    <div class="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
      <label class="block space-y-1">
        <span class="text-xs font-medium text-muted">Actor</span>
        <Input
          value={actorLocal}
          oninput={onActorInput}
          placeholder="alice@example.com"
          aria-label="Actor filter"
          data-testid="audit-actor-filter"
        />
      </label>
      <label class="block space-y-1">
        <span class="text-xs font-medium text-muted">Action prefix</span>
        <Input
          value={actionPrefixLocal}
          oninput={onActionPrefixInput}
          placeholder="settings."
          aria-label="Action prefix filter"
          data-testid="audit-action-prefix-filter"
        />
      </label>
      <label class="block space-y-1">
        <span class="text-xs font-medium text-muted">Target type</span>
        <select
          value={selectedTarget}
          onchange={(e) =>
            updateUrl({ target_type: (e.target as HTMLSelectElement).value || null })}
          class="h-9 w-full rounded-md border border-border-default bg-base px-2 text-sm text-default focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {#each targetTypes as t (t.value)}
            <option value={t.value}>{t.label}</option>
          {/each}
        </select>
      </label>
      <div class="space-y-1">
        <span class="text-xs font-medium text-muted">Range</span>
        <div class="flex h-9 items-center gap-1 rounded-md border border-border-default p-0.5">
          {#each ranges as r (r.value)}
            <button
              type="button"
              onclick={() => updateUrl({ range: r.value })}
              class={cn(
                'flex-1 rounded-sm px-2 py-1 text-xs font-medium transition-colors',
                range === r.value ? 'bg-accent-bg text-accent-text' : 'text-muted hover:bg-subtle',
              )}
              aria-pressed={range === r.value}
            >
              {r.label}
            </button>
          {/each}
        </div>
      </div>
    </div>

    {#if range === 'custom'}
      <div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <label class="block space-y-1">
          <span class="text-xs font-medium text-muted">Since (ISO 8601)</span>
          <Input
            value={since}
            oninput={(e) => updateUrl({ since: (e.target as HTMLInputElement).value || null })}
            placeholder="2026-01-01T00:00:00Z"
            aria-label="Since"
          />
        </label>
        <label class="block space-y-1">
          <span class="text-xs font-medium text-muted">Until (ISO 8601)</span>
          <Input
            value={until}
            oninput={(e) => updateUrl({ until: (e.target as HTMLInputElement).value || null })}
            placeholder="2026-01-31T23:59:59Z"
            aria-label="Until"
          />
        </label>
      </div>
    {/if}

    <div class="flex flex-wrap items-center gap-2">
      <span class="text-xs font-medium text-muted">Actions</span>
      {#each ALL_AUDIT_ACTIONS as a (a)}
        {@const on = selectedActions.includes(a)}
        <button
          type="button"
          onclick={() => toggleAction(a)}
          class={cn(
            'rounded-full border px-2.5 py-0.5 font-mono text-xs transition-colors',
            on
              ? 'border-accent bg-accent-bg text-accent-text'
              : 'border-border-default text-muted hover:bg-subtle',
          )}
          aria-pressed={on}
        >
          {a}
        </button>
      {/each}
    </div>

    <div class="flex items-center justify-between">
      <button
        type="button"
        class="text-xs text-accent-text underline-offset-4 hover:underline"
        onclick={clearFilters}
      >
        Clear filters
      </button>
      <span class="text-xs text-muted" data-testid="audit-count">
        {#if $audit.isPending && !$audit.data}
          Loading…
        {:else}
          Showing {events.length} of {total} events
        {/if}
      </span>
    </div>
  </div>

  {#if $audit.isPending && !$audit.data}
    <div class="space-y-2" aria-busy="true">
      {#each [0, 1, 2, 3] as i (i)}
        <div class="h-12 animate-pulse rounded-md bg-subtle"></div>
      {/each}
    </div>
  {:else if $audit.isError}
    <Card>
      <CardContent class="space-y-3 py-6">
        <p class="text-sm text-muted">
          Could not load audit log: {$audit.error?.message ?? 'unknown error'}.
        </p>
        <Button size="sm" onclick={() => void $audit.refetch()}>Reload</Button>
      </CardContent>
    </Card>
  {:else if events.length === 0}
    <Card>
      <CardContent class="flex flex-col items-center gap-3 py-12 text-center">
        <ListTree class="size-8 text-muted" aria-hidden="true" />
        <p class="text-sm text-muted">No events match these filters.</p>
      </CardContent>
    </Card>
  {:else}
    <ol class="list-none">
      {#each events as ev (ev.id)}
        <AuditEvent event={ev} />
      {/each}
    </ol>
    {#if $audit.hasNextPage}
      <div class="flex justify-center pt-2">
        <Button
          variant="outline"
          size="sm"
          onclick={() => void $audit.fetchNextPage()}
          disabled={$audit.isFetchingNextPage}
        >
          {#if $audit.isFetchingNextPage}
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
