<script lang="ts">
  import { CheckCircle2, Clock, Server, ShieldAlert } from '@lucide/svelte';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { resolve } from '$app/paths';
  import { Card, CardContent, CardHeader, CardTitle } from '$lib/components/ui/card';
  import { Button } from '$lib/components/ui/button';
  import { Badge } from '$lib/components/ui/badge';
  import MetricCard from '$lib/components/app/MetricCard.svelte';
  import HostTable from '$lib/components/app/HostTable.svelte';
  import HostFilters from '$lib/components/app/HostFilters.svelte';
  import LiveBadge from '$lib/components/app/LiveBadge.svelte';
  import BulkActionBar from '$lib/components/app/BulkActionBar.svelte';
  import { createHostSelection } from '$lib/components/app/host-selection.svelte';
  import { createOverviewQuery, createHostsQuery, type HostsParams } from '$lib/queries';
  import { runeReadable } from '$lib/queries/reactive.svelte';
  import { getLiveStream } from '$lib/queries/live-context';
  import type { HostStatus } from '$lib/api';
  import { userStore } from '$lib/stores/user.svelte';
  import { ApiError } from '$lib/api';

  const live = getLiveStream();

  // ---- Filters bound to URL ----
  const params: HostsParams = $derived.by(() => {
    const sp = $page.url.searchParams;
    const status = sp.get('status') as HostStatus | null;
    return {
      q: sp.get('q') ?? undefined,
      group: sp.get('group') ?? undefined,
      status: status ?? undefined,
      window: sp.get('window') ?? '5m',
    };
  });

  const overview = createOverviewQuery();
  const hosts = createHostsQuery(runeReadable(() => params));

  function trendDirection(now: number, before: number): 'up' | 'down' | 'neutral' {
    const diff = now - before;
    if (Math.abs(diff) < 0.1) return 'neutral';
    return diff > 0 ? 'up' : 'down';
  }

  function clearFilters(): void {
    void goto(resolve('/'), { keepFocus: true, noScroll: true, replaceState: true });
  }

  function reload(): void {
    void $overview.refetch();
    void $hosts.refetch();
  }

  const isAuthError = $derived(
    ($hosts.error instanceof ApiError && $hosts.error.status === 401) ||
      ($overview.error instanceof ApiError && $overview.error.status === 401),
  );

  const loginNext = $derived(encodeURIComponent($page.url.pathname + $page.url.search));

  // ---- Multi-select state ----
  // The selection store backs the Fleet table checkboxes + the floating
  // action bar. The actual "Issue command" dialog is wired in a follow-up
  // commit; for now the bar's onIssue is a no-op so users can still see
  // the affordance and clear the selection.
  const selection = createHostSelection();

  const selectedHostnames = $derived.by(() => {
    const all = $hosts.data?.hosts ?? [];
    const byId = new Map(all.map((h) => [h.id, h.hostname]));
    return selection.ids.map((id) => byId.get(id) ?? id);
  });
  const previewLabels = $derived(selectedHostnames.slice(0, 3));

  function openBulkDialog(): void {
    // Hooked up in the next commit (BulkIssueCommandDialog).
  }
</script>

<svelte:head>
  <title>Fleet · Remote-Pulse</title>
</svelte:head>

<section class="space-y-6">
  <header class="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
    <div>
      <h1 class="text-2xl font-bold tracking-tight">Fleet</h1>
      <p class="text-sm text-muted">
        Overview of every host reporting to Remote-Pulse.
        {#if userStore.value?.user_email}
          <span class="ml-1">
            Signed in as <span class="font-mono">{userStore.value.user_email}</span>
            {#if userStore.value.user_role}
              <Badge variant="outline" class="ml-1 align-middle">{userStore.value.user_role}</Badge>
            {/if}
          </span>
        {/if}
      </p>
    </div>
    {#if live}
      <LiveBadge state={live.state} class="self-start sm:self-auto" />
    {/if}
  </header>

  <!-- ============ Overview metrics ============ -->
  <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
    {#if $overview.isPending && !$overview.data}
      {#each [0, 1, 2, 3] as i (i)}
        <MetricCard label="…" value="—" loading Icon={Server} />
      {/each}
    {:else if $overview.data}
      {@const o = $overview.data}
      <MetricCard label="Total" value={String(o.total)} hint="fleet size" Icon={Server} />
      <MetricCard
        label="Online"
        value={`${o.online_pct.toFixed(0)}%`}
        hint={`${o.online} hosts`}
        tone="success"
        Icon={CheckCircle2}
        trend={{
          value: o.online_pct - o.online_pct_24h_ago,
          direction: trendDirection(o.online_pct, o.online_pct_24h_ago),
          unit: '%',
        }}
      />
      <MetricCard label="Stale" value={String(o.stale)} hint="60-180s" tone="warn" Icon={Clock} />
      <MetricCard
        label="Pending"
        value={String(o.pending_approvals)}
        hint="approvals"
        tone="danger"
        Icon={ShieldAlert}
      />
    {:else if $overview.isError}
      <Card class="col-span-full">
        <CardHeader>
          <CardTitle>Could not load overview</CardTitle>
        </CardHeader>
        <CardContent class="space-y-3">
          <p class="text-sm text-muted">
            {$overview.error?.message ?? 'Unknown error.'}
          </p>
          <div class="flex items-center gap-2">
            <Button onclick={reload} size="sm">Reload</Button>
            {#if isAuthError}
              <Button href={`/auth/login?next=${loginNext}`} variant="outline" size="sm">
                Sign in
              </Button>
            {/if}
          </div>
        </CardContent>
      </Card>
    {/if}
  </div>

  <!-- ============ Filters ============ -->
  <HostFilters groups={$hosts.data?.groups ?? []} />

  <!-- ============ Hosts table ============ -->
  {#if $hosts.isPending && !$hosts.data}
    <div class="space-y-2" aria-busy="true" aria-live="polite">
      {#each [0, 1, 2, 3, 4] as i (i)}
        <div class="h-12 animate-pulse rounded-md border border-border-subtle bg-subtle"></div>
      {/each}
    </div>
  {:else if $hosts.isError}
    <Card>
      <CardHeader>
        <CardTitle>Could not load hosts</CardTitle>
      </CardHeader>
      <CardContent class="space-y-3">
        <p class="text-sm text-muted">
          {$hosts.error?.message ?? 'Unknown error.'}
        </p>
        <div class="flex items-center gap-2">
          <Button onclick={reload} size="sm">Reload</Button>
          {#if isAuthError}
            <Button href={`/auth/login?next=${loginNext}`} variant="outline" size="sm">
              Sign in
            </Button>
          {/if}
        </div>
      </CardContent>
    </Card>
  {:else if $hosts.data && $hosts.data.hosts.length === 0}
    <Card>
      <CardContent class="flex flex-col items-center gap-3 py-12 text-center">
        <Server class="size-8 text-muted" aria-hidden="true" />
        <p class="text-sm text-muted">No hosts match your filters.</p>
        <Button variant="outline" size="sm" onclick={clearFilters}>Clear filters</Button>
      </CardContent>
    </Card>
  {:else if $hosts.data}
    <HostTable hosts={$hosts.data.hosts} {selection} />
  {/if}
</section>

<BulkActionBar
  count={selection.count}
  {previewLabels}
  totalLabels={selectedHostnames.length}
  onIssue={openBulkDialog}
  onClear={() => selection.clear()}
/>
