<script lang="ts">
  import { ArrowLeft, Server } from '@lucide/svelte';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { base, resolve } from '$app/paths';
  import { SvelteURLSearchParams } from 'svelte/reactivity';
  import { Card, CardContent, CardHeader, CardTitle } from '$lib/components/ui/card';
  import { Button } from '$lib/components/ui/button';
  import { Badge } from '$lib/components/ui/badge';
  import { Tabs, TabsList, TabsTrigger, TabsContent } from '$lib/components/ui/tabs';
  import HostStatusBadge from '$lib/components/app/HostStatusBadge.svelte';
  import TimeseriesChart from '$lib/components/app/TimeseriesChart.svelte';
  import WindowSelector from '$lib/components/app/WindowSelector.svelte';
  import RelativeTime from '$lib/components/app/RelativeTime.svelte';
  import LiveBadge from '$lib/components/app/LiveBadge.svelte';
  import IssueCommandDialog from '$lib/components/app/IssueCommandDialog.svelte';
  import DeleteHostDialog from '$lib/components/app/DeleteHostDialog.svelte';
  import {
    createHostDetailQuery,
    createTimeseriesQuery,
    type TimeseriesParams,
  } from '$lib/queries';
  import { runeReadable } from '$lib/queries/reactive.svelte';
  import { getLiveStream } from '$lib/queries/live-context';
  import { formatUptime } from '$lib/utils/relative-time';
  import { userStore } from '$lib/stores/user.svelte';

  type Data = { hostId: string };
  const { data }: { data: Data } = $props();

  const live = getLiveStream();

  // ---- Metrics tab state, persisted to URL ----
  const window = $derived($page.url.searchParams.get('window') ?? '5m');

  const allSeries = [
    { key: 'cpu_pct', label: 'CPU %', defaultOn: true },
    { key: 'mem_pct', label: 'Memory %', defaultOn: true },
    { key: 'load_1m', label: 'Load 1m', defaultOn: true },
    { key: 'net_rx_kbps', label: 'Net RX kbps', defaultOn: false },
    { key: 'net_tx_kbps', label: 'Net TX kbps', defaultOn: false },
  ] as const;

  let enabledSeries = $state<Record<string, boolean>>(
    Object.fromEntries(allSeries.map((s) => [s.key, s.defaultOn])),
  );

  const tsParams: TimeseriesParams = $derived({
    window,
    series: allSeries.filter((s) => enabledSeries[s.key]).map((s) => s.key),
  });

  const hostQuery = createHostDetailQuery(runeReadable(() => data.hostId));
  const tsQuery = createTimeseriesQuery(
    runeReadable(() => data.hostId),
    runeReadable(() => tsParams),
  );

  let activeTab = $state<'metrics' | 'commands' | 'logs' | 'keys'>('metrics');
  let issueOpen = $state(false);
  let deleteOpen = $state(false);

  // Show the "Danger zone" only to admins. Non-admins with a row-level
  // `host.delete` grant are gated client-side here for UX clarity; the
  // server is the source of truth and answers 403 if a stale grant has
  // already been revoked. Granting non-admins visibility would require
  // an extra `/v1/dash/settings/users/{me}/permissions` round-trip per
  // host page — not worth the latency for a marginal UX win.
  const canDeleteHost = $derived(userStore.value?.user_role === 'admin');

  function updateWindow(next: string): void {
    const sp = new SvelteURLSearchParams($page.url.searchParams);
    if (next === '5m') sp.delete('window');
    else sp.set('window', next);
    const qs = sp.toString();
    const path = resolve('/hosts/[id]', { id: data.hostId });
    // `path` was produced by `resolve()` directly above; we append the
    // serialised query string. eslint-plugin-svelte can't trace through
    // the template, so silence it locally.
    // eslint-disable-next-line svelte/no-navigation-without-resolve
    void goto(`${path}${qs ? `?${qs}` : ''}` as `/${string}`, {
      keepFocus: true,
      noScroll: true,
      replaceState: true,
    });
  }
</script>

<svelte:head>
  <title>{$hostQuery.data?.hostname ?? 'Host'} · Remote-Pulse</title>
</svelte:head>

<section class="space-y-6">
  <div>
    <Button href={`${base}/`} variant="ghost" size="sm" class="-ml-2">
      <ArrowLeft class="size-4" aria-hidden="true" />
      Fleet
    </Button>
  </div>

  {#if $hostQuery.isPending && !$hostQuery.data}
    <div class="space-y-3" aria-busy="true">
      <div class="h-7 w-56 animate-pulse rounded bg-subtle"></div>
      <div class="h-4 w-80 animate-pulse rounded bg-subtle"></div>
    </div>
  {:else if $hostQuery.data}
    {@const host = $hostQuery.data}
    <header class="space-y-2">
      <div class="flex items-center justify-between gap-4">
        <div class="flex items-center gap-3">
          <Server class="size-6 text-muted" aria-hidden="true" />
          <h1 class="font-mono text-2xl font-semibold tracking-tight">{host.hostname}</h1>
          <HostStatusBadge status={host.status} lastSeenSecondsAgo={host.last_seen_seconds_ago} />
        </div>
        <div class="flex items-center gap-2">
          <Button size="sm" data-testid="host-issue-command-btn" onclick={() => (issueOpen = true)}>
            Issue command
          </Button>
          {#if live}
            <LiveBadge state={live.state} />
          {/if}
        </div>
      </div>
      <dl class="grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-3 lg:grid-cols-6">
        <div>
          <dt class="text-muted">Group</dt>
          <dd class="font-mono">{host.group_name}</dd>
        </div>
        <div>
          <dt class="text-muted">OS</dt>
          <dd class="font-mono">{host.os_family ?? '—'}</dd>
        </div>
        <div>
          <dt class="text-muted">Agent</dt>
          <dd class="font-mono">{host.agent_version ?? '—'}</dd>
        </div>
        <div>
          <dt class="text-muted">Tailscale</dt>
          <dd class="font-mono">{host.tailscale_ip ?? '—'}</dd>
        </div>
        <div>
          <dt class="text-muted">Uptime</dt>
          <dd class="font-mono">{formatUptime(host.current.uptime_s)}</dd>
        </div>
        <div>
          <dt class="text-muted">Last seen</dt>
          <dd class="font-mono">
            <RelativeTime iso={host.last_seen_at} secondsAgo={host.last_seen_seconds_ago} />
          </dd>
        </div>
      </dl>
    </header>

    <Tabs bind:value={activeTab}>
      <TabsList>
        <TabsTrigger value="metrics">Metrics</TabsTrigger>
        <TabsTrigger value="commands">Commands</TabsTrigger>
        <TabsTrigger value="logs">Logs</TabsTrigger>
        <TabsTrigger value="keys">Keys</TabsTrigger>
      </TabsList>

      <!-- ====== Metrics ====== -->
      <TabsContent value="metrics" class="space-y-4">
        <div class="flex flex-wrap items-center gap-3">
          <WindowSelector value={window} onchange={updateWindow} />
          <div class="flex flex-wrap items-center gap-2 text-xs">
            {#each allSeries as s (s.key)}
              <label
                class="inline-flex items-center gap-1.5 rounded-md border border-border-default px-2 py-1 text-default"
              >
                <input
                  type="checkbox"
                  bind:checked={enabledSeries[s.key]}
                  class="size-3 accent-current"
                />
                <span class="font-mono">{s.label}</span>
              </label>
            {/each}
          </div>
        </div>

        <div class="grid grid-cols-1 gap-4">
          <div class="rounded-lg border border-border-default bg-elevated p-3 sm:p-4">
            <TimeseriesChart
              data={$tsQuery.data}
              series={[
                ...(enabledSeries.cpu_pct
                  ? [
                      {
                        key: 'cpu_pct' as const,
                        label: 'CPU %',
                        color: 'var(--accent-solid)',
                        unit: '%',
                      },
                    ]
                  : []),
                ...(enabledSeries.mem_pct
                  ? [
                      {
                        key: 'mem_pct' as const,
                        label: 'Memory %',
                        color: 'var(--warn-solid)',
                        unit: '%',
                      },
                    ]
                  : []),
              ]}
              height={220}
              title="CPU & Memory"
              yMin={0}
              yMax={100}
            />
          </div>

          {#if enabledSeries.load_1m}
            <div class="rounded-lg border border-border-default bg-elevated p-3 sm:p-4">
              <TimeseriesChart
                data={$tsQuery.data}
                series={[
                  {
                    key: 'load_1m',
                    label: 'Load 1m',
                    color: 'var(--success-solid)',
                  },
                ]}
                height={180}
                title="Load average (1m)"
                yMin={0}
              />
            </div>
          {/if}

          {#if enabledSeries.net_rx_kbps || enabledSeries.net_tx_kbps}
            <div class="rounded-lg border border-border-default bg-elevated p-3 sm:p-4">
              <TimeseriesChart
                data={$tsQuery.data}
                series={[
                  ...(enabledSeries.net_rx_kbps
                    ? [
                        {
                          key: 'net_rx_kbps' as const,
                          label: 'RX kbps',
                          color: 'var(--accent-solid)',
                          unit: ' kbps',
                        },
                      ]
                    : []),
                  ...(enabledSeries.net_tx_kbps
                    ? [
                        {
                          key: 'net_tx_kbps' as const,
                          label: 'TX kbps',
                          color: 'var(--danger-solid)',
                          unit: ' kbps',
                        },
                      ]
                    : []),
                ]}
                height={180}
                title="Network"
                yMin={0}
              />
            </div>
          {/if}

          <Card>
            <CardHeader>
              <CardTitle>Current values</CardTitle>
            </CardHeader>
            <CardContent>
              <dl class="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-4">
                <div>
                  <dt class="text-xs text-muted">CPU</dt>
                  <dd class="font-mono text-lg">
                    {host.current.cpu_pct === null ? '—' : `${host.current.cpu_pct.toFixed(1)}%`}
                  </dd>
                </div>
                <div>
                  <dt class="text-xs text-muted">Memory</dt>
                  <dd class="font-mono text-lg">
                    {host.current.mem_pct === null ? '—' : `${host.current.mem_pct.toFixed(1)}%`}
                  </dd>
                </div>
                <div>
                  <dt class="text-xs text-muted">Load 1m</dt>
                  <dd class="font-mono text-lg">
                    {host.current.load_1m === null ? '—' : host.current.load_1m.toFixed(2)}
                  </dd>
                </div>
                <div>
                  <dt class="text-xs text-muted">Uptime</dt>
                  <dd class="font-mono text-lg">{formatUptime(host.current.uptime_s)}</dd>
                </div>
              </dl>
            </CardContent>
          </Card>
        </div>

        {#if $tsQuery.isError}
          <Card>
            <CardContent class="py-4">
              <p class="text-sm text-muted">
                Could not load time series: {$tsQuery.error?.message ?? 'unknown error'}.
              </p>
            </CardContent>
          </Card>
        {/if}
      </TabsContent>

      <!-- ====== Other tabs (placeholders) ====== -->
      <TabsContent value="commands">
        <Card>
          <CardHeader>
            <CardTitle>Commands</CardTitle>
          </CardHeader>
          <CardContent>
            <p class="text-sm text-muted">Coming in Phase 2.</p>
          </CardContent>
        </Card>
      </TabsContent>

      <TabsContent value="logs">
        <Card>
          <CardHeader>
            <CardTitle>Logs</CardTitle>
          </CardHeader>
          <CardContent>
            <p class="text-sm text-muted">Coming in Phase 2.</p>
          </CardContent>
        </Card>
      </TabsContent>

      <TabsContent value="keys">
        <Card>
          <CardHeader>
            <CardTitle>Keys</CardTitle>
          </CardHeader>
          <CardContent>
            <p class="text-sm text-muted">Coming in Phase 4.</p>
          </CardContent>
        </Card>
      </TabsContent>
    </Tabs>

    {#if canDeleteHost}
      <section
        class="mt-6 rounded-lg border border-danger/40 bg-elevated p-4 sm:p-6"
        aria-labelledby="danger-zone-heading"
      >
        <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div class="space-y-1">
            <h2 id="danger-zone-heading" class="text-sm font-semibold text-danger">Danger zone</h2>
            <p class="text-xs text-muted">
              Permanently delete <span class="font-mono">{host.hostname}</span> and all its history (heartbeats,
              commands, SSH keys). This cannot be undone.
            </p>
          </div>
          <Button
            variant="danger"
            size="sm"
            data-testid="host-delete-btn"
            onclick={() => (deleteOpen = true)}
          >
            Delete host
          </Button>
        </div>
      </section>

      <DeleteHostDialog
        bind:open={deleteOpen}
        onOpenChange={(v) => (deleteOpen = v)}
        hostId={host.id}
        hostname={host.hostname}
        onDeleted={() => {
          // Send the user back to the fleet overview — the host row will
          // already be gone thanks to the optimistic patch. The base
          // prefix is the SPA mount-point; this is intentionally a
          // template literal so eslint-plugin-svelte sees `goto(base + '/')`
          // rather than a magic string it can't resolve.
          // eslint-disable-next-line svelte/no-navigation-without-resolve
          void goto(`${base}/`);
        }}
      />
    {/if}

    <IssueCommandDialog
      bind:open={issueOpen}
      onOpenChange={(v) => (issueOpen = v)}
      initialHostId={data.hostId}
    />
  {:else if $hostQuery.isError}
    <Card>
      <CardHeader>
        <CardTitle>Could not load host</CardTitle>
      </CardHeader>
      <CardContent class="space-y-3">
        <p class="text-sm text-muted">
          {$hostQuery.error?.message ?? 'Unknown error.'}
        </p>
        <div class="flex items-center gap-2">
          <Button onclick={() => void $hostQuery.refetch()} size="sm">Reload</Button>
          <Button href={`${base}/`} variant="outline" size="sm">Back to fleet</Button>
        </div>
      </CardContent>
    </Card>
  {:else if !$hostQuery.isPending}
    <Card>
      <CardHeader>
        <CardTitle>Host not found</CardTitle>
      </CardHeader>
      <CardContent class="space-y-3">
        <p class="text-sm text-muted">
          No host with id <span class="font-mono">{data.hostId}</span> is currently reporting.
        </p>
        <Badge variant="muted">404</Badge>
        <div>
          <Button href={`${base}/`} variant="outline" size="sm">Back to fleet</Button>
        </div>
      </CardContent>
    </Card>
  {/if}
</section>
