<script lang="ts">
  import { Loader2, ListTree } from '@lucide/svelte';
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
  import { createAuditQuery } from '$lib/queries';
  import { runeReadable } from '$lib/queries/reactive.svelte';
  import { getLiveStream } from '$lib/queries/live-context';
  import {
    ALL_AUDIT_ACTIONS,
    type AuditAction,
    type AuditQueryParams,
    type AuditTargetType,
  } from '$lib/api';

  const live = getLiveStream();

  type Range = '24h' | '7d' | '30d' | 'custom';

  function sinceFor(range: Range): string | undefined {
    if (range === 'custom') return undefined;
    const now = Date.now();
    const offset = range === '24h' ? 86_400_000 : range === '7d' ? 604_800_000 : 2_592_000_000;
    return new Date(now - offset).toISOString();
  }

  const params: AuditQueryParams = $derived.by(() => {
    const sp = $page.url.searchParams;
    const actor = sp.get('actor') ?? undefined;
    const actionList = sp
      .getAll('action')
      .filter((a): a is AuditAction => (ALL_AUDIT_ACTIONS as ReadonlyArray<string>).includes(a));
    const targetType = (sp.get('target_type') as AuditTargetType | null) ?? undefined;
    const rangeRaw = (sp.get('range') ?? '7d') as Range;
    const since = rangeRaw === 'custom' ? (sp.get('since') ?? undefined) : sinceFor(rangeRaw);
    const until = rangeRaw === 'custom' ? (sp.get('until') ?? undefined) : undefined;
    return {
      actor,
      action: actionList.length > 0 ? actionList : undefined,
      target_type: targetType,
      since,
      until,
      limit: 100,
    };
  });

  const audit = createAuditQuery(runeReadable(() => params));
  const events = $derived($audit.data?.pages.flatMap((p) => p.events) ?? []);

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

  const ranges: ReadonlyArray<{ value: Range; label: string }> = [
    { value: '24h', label: '24h' },
    { value: '7d', label: '7d' },
    { value: '30d', label: '30d' },
    { value: 'custom', label: 'Custom' },
  ];

  const targetTypes: ReadonlyArray<{ value: AuditTargetType | ''; label: string }> = [
    { value: '', label: 'Any target' },
    { value: 'command', label: 'Command' },
    { value: 'host', label: 'Host' },
    { value: 'enrollment', label: 'Enrollment' },
    { value: 'user', label: 'User' },
  ];

  function clearFilters(): void {
    actorLocal = '';
    updateUrl({
      actor: null,
      action: [],
      target_type: null,
      range: '7d',
      since: null,
      until: null,
    });
  }
</script>

<svelte:head>
  <title>Audit · Remote-Pulse</title>
</svelte:head>

<section class="space-y-6">
  <header class="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
    <div>
      <h1 class="text-2xl font-bold tracking-tight">Audit log</h1>
      <p class="text-sm text-muted">Every state-changing event in the system, append-only.</p>
    </div>
    {#if live}
      <LiveBadge state={live.state} />
    {/if}
  </header>

  <div class="space-y-3 rounded-lg border border-border-default bg-elevated p-3">
    <div class="grid grid-cols-1 gap-2 sm:grid-cols-3">
      <label class="block space-y-1">
        <span class="text-xs font-medium text-muted">Actor</span>
        <Input
          value={actorLocal}
          oninput={onActorInput}
          placeholder="alice@example.com"
          aria-label="Actor filter"
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

    <div>
      <button
        type="button"
        class="text-xs text-accent-text underline-offset-4 hover:underline"
        onclick={clearFilters}
      >
        Clear filters
      </button>
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
