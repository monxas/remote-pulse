<script lang="ts">
  import { BarChart3, CheckCircle2, ListTree, Loader2, Server, Activity } from '@lucide/svelte';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { resolve } from '$app/paths';
  import { SvelteURLSearchParams } from 'svelte/reactivity';
  import { Card, CardContent, CardHeader, CardTitle } from '$lib/components/ui/card';
  import { Button } from '$lib/components/ui/button';
  import MetricCard from '$lib/components/app/MetricCard.svelte';
  import PullToRefresh from '$lib/components/app/PullToRefresh.svelte';
  import { createStatsQuery } from '$lib/queries';
  import { runeReadable } from '$lib/queries/reactive.svelte';
  import { ALL_STATS_RANGES, type StatsRange } from '$lib/api';
  import { cn } from '$lib/utils';

  // ----- Range from URL ---------------------------------------------------
  function rangeFromSearch(sp: URLSearchParams): StatsRange {
    const raw = sp.get('range');
    return (ALL_STATS_RANGES as ReadonlyArray<string>).includes(raw ?? '')
      ? (raw as StatsRange)
      : '7d';
  }

  const range: StatsRange = $derived(rangeFromSearch($page.url.searchParams));

  function setRange(next: StatsRange): void {
    const sp = new SvelteURLSearchParams($page.url.searchParams);
    sp.set('range', next);
    const qs = sp.toString();
    const target = `${resolve('/stats')}${qs ? `?${qs}` : ''}` as `/${string}`;
    // eslint-disable-next-line svelte/no-navigation-without-resolve
    void goto(target, { keepFocus: true, noScroll: true, replaceState: true });
  }

  const stats = createStatsQuery(runeReadable(() => range));

  // ----- Derived display values ------------------------------------------
  const fleet = $derived($stats.data?.fleet);
  const commands = $derived($stats.data?.commands);
  const heartbeats = $derived($stats.data?.heartbeats);
  const uptimePerHost = $derived($stats.data?.uptime_per_host ?? []);
  const audit = $derived($stats.data?.audit_summary);

  const hasCommands = $derived((commands?.total ?? 0) > 0);
  const hasAudit = $derived((audit?.total_events ?? 0) > 0);
  const hasHosts = $derived((fleet?.total_hosts ?? 0) > 0);

  // Helper to format a percentage like ``98.42`` → ``"98.42%"``.
  function pct(v: number | undefined | null, decimals = 1): string {
    if (v === undefined || v === null) return '—';
    return `${v.toFixed(decimals)}%`;
  }

  // Successful command success-rate display: 0.972 → "97.2%".
  function rate(v: number | undefined | null): string {
    if (v === undefined || v === null) return '—';
    return `${(v * 100).toFixed(1)}%`;
  }

  function reload(): void {
    void $stats.refetch();
  }

  // ----- Chart helpers (inline SVG; lighter than wiring uPlot for bars) --
  // The Daily Commands chart needs a stacked bar (succeeded vs failed).
  // The horizontal bars (uptime, audit) only need a width = pct calc.
  const dailyMax = $derived.by(() => {
    const buckets = commands?.daily ?? [];
    return buckets.length === 0 ? 0 : Math.max(1, ...buckets.map((d) => d.issued));
  });

  const topUptime = $derived(uptimePerHost.slice(0, 12));
  const topActions = $derived(audit?.by_action.slice(0, 10) ?? []);
  const topActors = $derived(audit?.by_actor.slice(0, 5) ?? []);

  // Audit / actor bars share an "ordered by count desc" model, so the max
  // is always the first entry. Guard against an empty list to avoid /0.
  const actionMax = $derived(topActions[0]?.count ?? 1);
  const actorMax = $derived(topActors[0]?.count ?? 1);

  // ----- Audit events sparkline (v1.0.15) -------------------------------
  // 60×20 inline SVG polyline. Driven directly off the new
  // `audit_summary.daily` payload. When retention purges old events the
  // leftmost cell drops to zero — visible without any clicks.
  const auditDaily = $derived(audit?.daily ?? []);
  const auditDailyMax = $derived.by(() => {
    if (auditDaily.length === 0) return 0;
    return Math.max(1, ...auditDaily.map((d) => d.count));
  });
  const auditSparklinePath = $derived.by(() => {
    if (auditDaily.length === 0) return '';
    const W = 60;
    const H = 20;
    const n = auditDaily.length;
    // Single-point sparkline degenerates to a centred dot; render as a
    // tiny horizontal stroke so the SVG isn't visually empty.
    if (n === 1) return `M0 ${H / 2} L${W} ${H / 2}`;
    const stepX = W / (n - 1);
    return auditDaily
      .map((d, i) => {
        const x = i * stepX;
        const y = H - (d.count / auditDailyMax) * H;
        return `${i === 0 ? 'M' : 'L'}${x.toFixed(2)} ${y.toFixed(2)}`;
      })
      .join(' ');
  });

  // Collapsible state for tables -----------------------------------------
  let showByType = $state(false);
  let showUptimeTable = $state(false);
</script>

<svelte:head>
  <title>Statistics — remote-pulse</title>
</svelte:head>

<PullToRefresh onRefresh={reload}>
  <header class="mb-4 flex flex-wrap items-center justify-between gap-3">
    <div class="flex items-center gap-2">
      <BarChart3 class="size-5 text-muted" aria-hidden="true" />
      <h1 class="text-xl font-semibold tracking-tight">Statistics</h1>
    </div>
    <div
      class="inline-flex rounded-md border border-border-default bg-elevated p-0.5"
      role="radiogroup"
      aria-label="Time range"
      data-testid="stats-range-selector"
    >
      {#each ALL_STATS_RANGES as r (r)}
        <button
          type="button"
          role="radio"
          aria-checked={range === r}
          data-testid="stats-range-{r}"
          class={cn(
            'touch-target rounded-sm px-3 py-1 text-sm font-medium transition-colors',
            range === r
              ? 'bg-subtle text-default'
              : 'text-muted hover:bg-subtle/60 hover:text-default',
          )}
          onclick={() => setRange(r)}
        >
          {r}
        </button>
      {/each}
    </div>
  </header>

  {#if $stats.isLoading && !$stats.data}
    <div class="flex h-32 items-center justify-center gap-2 text-muted" data-testid="stats-loading">
      <Loader2 class="size-4 animate-spin" aria-hidden="true" />
      <span>Loading statistics…</span>
    </div>
  {:else if $stats.error}
    <Card class="border-danger-border bg-danger-subtle">
      <CardContent class="py-4 text-sm text-danger-text">
        Could not load statistics: {$stats.error.message}
        <Button variant="outline" size="sm" class="ml-2" onclick={reload} data-testid="stats-retry">
          Retry
        </Button>
      </CardContent>
    </Card>
  {:else}
    <!-- KPI cards ------------------------------------------------------ -->
    <section
      class="grid grid-cols-2 gap-3 sm:grid-cols-2 md:grid-cols-4"
      aria-label="Key performance indicators"
      data-testid="stats-kpi-cards"
    >
      <MetricCard
        label="Total hosts"
        value={String(fleet?.total_hosts ?? 0)}
        hint={fleet ? `${fleet.online_now} online` : undefined}
        tone="default"
        Icon={Server}
      />
      <MetricCard
        label="Fleet uptime"
        value={pct(fleet?.uptime_percent, 2)}
        hint={range}
        tone="success"
        Icon={Activity}
      />
      <MetricCard
        label="Commands success"
        value={hasCommands ? rate(commands?.success_rate) : '—'}
        hint={commands ? `${commands.succeeded}/${commands.total}` : undefined}
        tone={commands && commands.failed === 0 ? 'success' : 'warn'}
        Icon={CheckCircle2}
      />
      <!-- Audit events KPI with inline sparkline (v1.0.15). Using a bespoke
           Card here instead of MetricCard so we can lay out the sparkline
           below the count — MetricCard has no slot. The sparkline tracks
           per-day counts over the selected range, so when retention
           purges old events the leftmost band drops visibly. -->
      <Card data-testid="stats-audit-card">
        <CardHeader class="flex flex-row items-center justify-between gap-2 pb-2">
          <CardTitle class="text-sm font-medium text-muted">Audit events</CardTitle>
          <ListTree class="size-4 text-muted" aria-hidden="true" />
        </CardHeader>
        <CardContent>
          <div class="flex items-baseline justify-between gap-2">
            <span
              class="font-mono text-2xl font-semibold tracking-tight"
              data-testid="stats-audit-total"
            >
              {audit?.total_events ?? 0}
            </span>
            <span class="text-xs text-muted">{range}</span>
          </div>
          {#if auditDaily.length > 0}
            <svg
              viewBox="0 0 60 20"
              preserveAspectRatio="none"
              class="mt-2 h-6 w-full"
              role="img"
              aria-label={`Audit events per day, peak ${auditDailyMax}`}
              data-testid="stats-audit-sparkline"
            >
              <path
                d={auditSparklinePath}
                fill="none"
                stroke="currentColor"
                stroke-width="1"
                stroke-linecap="round"
                stroke-linejoin="round"
                class="text-accent"
              />
            </svg>
          {:else}
            <div class="mt-2 h-6" aria-hidden="true"></div>
          {/if}
        </CardContent>
      </Card>
    </section>

    <!-- Daily commands stacked bar chart ------------------------------ -->
    <section class="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Card data-testid="stats-daily-chart">
        <CardHeader class="pb-2">
          <CardTitle class="text-sm font-medium text-muted">Commands per day</CardTitle>
        </CardHeader>
        <CardContent>
          {#if !hasCommands || commands?.daily.length === 0}
            <p class="py-8 text-center text-sm text-muted">No activity in this range</p>
          {:else}
            <svg
              viewBox="0 0 600 160"
              preserveAspectRatio="none"
              class="w-full"
              style:height="160px"
              role="img"
              aria-label="Daily issued commands, stacked by outcome"
            >
              {#each commands?.daily ?? [] as bucket, i (bucket.day)}
                {@const bars = commands?.daily ?? []}
                {@const colW = bars.length ? 600 / bars.length : 0}
                {@const x = i * colW + colW * 0.15}
                {@const w = colW * 0.7}
                {@const okH = dailyMax ? (bucket.succeeded / dailyMax) * 140 : 0}
                {@const failH = dailyMax ? (bucket.failed / dailyMax) * 140 : 0}
                {@const totalH = okH + failH}
                <g>
                  <rect
                    {x}
                    y={150 - totalH}
                    width={w}
                    height={failH}
                    fill="var(--color-danger-bg, #ef4444)"
                    aria-hidden="true"
                  >
                    <title>{bucket.day}: {bucket.failed} failed</title>
                  </rect>
                  <rect
                    {x}
                    y={150 - okH}
                    width={w}
                    height={okH}
                    fill="var(--color-success-bg, #22c55e)"
                    aria-hidden="true"
                  >
                    <title>{bucket.day}: {bucket.succeeded} succeeded</title>
                  </rect>
                </g>
              {/each}
            </svg>
            <div class="mt-2 flex items-center justify-between text-xs text-muted">
              <span>{commands?.daily[0]?.day ?? ''}</span>
              <span class="inline-flex items-center gap-3">
                <span class="inline-flex items-center gap-1">
                  <span class="inline-block size-2 rounded-sm bg-success"></span>
                  succeeded
                </span>
                <span class="inline-flex items-center gap-1">
                  <span class="inline-block size-2 rounded-sm bg-danger"></span>
                  failed
                </span>
              </span>
              <span>{commands?.daily.at(-1)?.day ?? ''}</span>
            </div>
          {/if}
        </CardContent>
      </Card>

      <!-- Uptime per host -------------------------------------------- -->
      <Card data-testid="stats-uptime-chart">
        <CardHeader class="pb-2">
          <CardTitle class="text-sm font-medium text-muted">
            Uptime per host
            <span class="ml-1 font-normal">({topUptime.length})</span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {#if !hasHosts}
            <p class="py-8 text-center text-sm text-muted">No hosts visible to you</p>
          {:else}
            <ul class="space-y-1.5">
              {#each topUptime as h (h.hostname)}
                <li class="flex items-center gap-2 text-xs">
                  <span class="w-24 truncate font-mono text-muted" title={h.hostname}>
                    {h.hostname}
                  </span>
                  <span
                    class="relative h-3 flex-1 overflow-hidden rounded-sm bg-subtle"
                    aria-hidden="true"
                  >
                    <span
                      class="absolute inset-y-0 left-0 bg-success"
                      style:width="{Math.max(0.5, h.uptime_percent)}%"
                    ></span>
                  </span>
                  <span class="w-12 text-right font-mono tabular-nums">
                    {h.uptime_percent.toFixed(1)}%
                  </span>
                </li>
              {/each}
            </ul>
          {/if}
        </CardContent>
      </Card>

      <!-- Audit by action -------------------------------------------- -->
      <Card data-testid="stats-actions-chart">
        <CardHeader class="pb-2">
          <CardTitle class="text-sm font-medium text-muted">
            Top audit actions ({topActions.length})
          </CardTitle>
        </CardHeader>
        <CardContent>
          {#if !hasAudit}
            <p class="py-8 text-center text-sm text-muted">No audit activity in this range</p>
          {:else}
            <ul class="space-y-1.5">
              {#each topActions as a (a.action)}
                <li class="flex items-center gap-2 text-xs">
                  <span class="w-40 truncate font-mono text-muted" title={a.action}>
                    {a.action}
                  </span>
                  <span
                    class="relative h-3 flex-1 overflow-hidden rounded-sm bg-subtle"
                    aria-hidden="true"
                  >
                    <span
                      class="absolute inset-y-0 left-0 bg-info"
                      style:width="{(a.count / actionMax) * 100}%"
                    ></span>
                  </span>
                  <span class="w-10 text-right font-mono tabular-nums">{a.count}</span>
                </li>
              {/each}
            </ul>
          {/if}
        </CardContent>
      </Card>

      <!-- Audit by actor --------------------------------------------- -->
      <Card data-testid="stats-actors-chart">
        <CardHeader class="pb-2">
          <CardTitle class="text-sm font-medium text-muted">
            Top actors ({topActors.length})
          </CardTitle>
        </CardHeader>
        <CardContent>
          {#if !hasAudit}
            <p class="py-8 text-center text-sm text-muted">No audit activity in this range</p>
          {:else}
            <ul class="space-y-1.5">
              {#each topActors as a (a.actor)}
                <li class="flex items-center gap-2 text-xs">
                  <span class="w-40 truncate font-mono text-muted" title={a.actor}>
                    {a.actor}
                  </span>
                  <span
                    class="relative h-3 flex-1 overflow-hidden rounded-sm bg-subtle"
                    aria-hidden="true"
                  >
                    <span
                      class="absolute inset-y-0 left-0 bg-warn"
                      style:width="{(a.count / actorMax) * 100}%"
                    ></span>
                  </span>
                  <span class="w-10 text-right font-mono tabular-nums">{a.count}</span>
                </li>
              {/each}
            </ul>
          {/if}
        </CardContent>
      </Card>
    </section>

    <!-- Heartbeat summary band ---------------------------------------- -->
    {#if heartbeats}
      <section
        class="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4"
        data-testid="stats-heartbeat-band"
      >
        <MetricCard label="Total heartbeats" value={heartbeats.total.toLocaleString()} />
        <MetricCard label="Avg/host/min" value={heartbeats.per_host_avg_per_min.toFixed(2)} />
        <MetricCard
          label="Stale (now)"
          value={String(heartbeats.stale_events)}
          tone={heartbeats.stale_events > 0 ? 'warn' : 'default'}
        />
        <MetricCard
          label="Offline (now)"
          value={String(heartbeats.offline_events)}
          tone={heartbeats.offline_events > 0 ? 'danger' : 'default'}
        />
      </section>
    {/if}

    <!-- Collapsible tables -------------------------------------------- -->
    <section class="mt-6 space-y-3">
      <div>
        <button
          type="button"
          class="touch-target inline-flex items-center gap-2 rounded-md border border-border-default bg-elevated px-3 py-1.5 text-sm hover:bg-subtle/60"
          aria-expanded={showByType}
          onclick={() => (showByType = !showByType)}
          data-testid="stats-toggle-by-type"
        >
          Commands by type
          <span class="font-mono text-xs text-muted">({commands?.by_type.length ?? 0})</span>
        </button>
        {#if showByType}
          <div class="mt-2 overflow-hidden rounded-md border border-border-subtle">
            <table class="w-full text-sm">
              <thead class="bg-subtle/60 text-xs text-muted">
                <tr>
                  <th class="px-3 py-2 text-left font-medium">Type</th>
                  <th class="px-3 py-2 text-right font-medium">Count</th>
                </tr>
              </thead>
              <tbody>
                {#each commands?.by_type ?? [] as t (t.type)}
                  <tr class="border-t border-border-subtle">
                    <td class="px-3 py-2 font-mono">{t.type}</td>
                    <td class="px-3 py-2 text-right font-mono tabular-nums">{t.count}</td>
                  </tr>
                {:else}
                  <tr><td colspan="2" class="px-3 py-4 text-center text-muted">No commands</td></tr>
                {/each}
              </tbody>
            </table>
          </div>
        {/if}
      </div>

      <div>
        <button
          type="button"
          class="touch-target inline-flex items-center gap-2 rounded-md border border-border-default bg-elevated px-3 py-1.5 text-sm hover:bg-subtle/60"
          aria-expanded={showUptimeTable}
          onclick={() => (showUptimeTable = !showUptimeTable)}
          data-testid="stats-toggle-uptime-table"
        >
          Uptime per host (full)
          <span class="font-mono text-xs text-muted">({uptimePerHost.length})</span>
        </button>
        {#if showUptimeTable}
          <div class="mt-2 overflow-hidden rounded-md border border-border-subtle">
            <table class="w-full text-sm">
              <thead class="bg-subtle/60 text-xs text-muted">
                <tr>
                  <th class="px-3 py-2 text-left font-medium">Host</th>
                  <th class="px-3 py-2 text-right font-medium">Uptime</th>
                  <th class="px-3 py-2 text-right font-medium">Downtime (min)</th>
                </tr>
              </thead>
              <tbody>
                {#each uptimePerHost as h (h.hostname)}
                  <tr class="border-t border-border-subtle">
                    <td class="px-3 py-2 font-mono">{h.hostname}</td>
                    <td class="px-3 py-2 text-right font-mono tabular-nums">
                      {h.uptime_percent.toFixed(2)}%
                    </td>
                    <td class="px-3 py-2 text-right font-mono tabular-nums">
                      {h.downtime_minutes.toLocaleString()}
                    </td>
                  </tr>
                {:else}
                  <tr><td colspan="3" class="px-3 py-4 text-center text-muted">No hosts</td></tr>
                {/each}
              </tbody>
            </table>
          </div>
        {/if}
      </div>
    </section>
  {/if}
</PullToRefresh>
