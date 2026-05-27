<script lang="ts">
  /**
   * Webhook deliveries — admin-only log of recent attempts for one hook.
   *
   * The server keeps a JSONB sliding window of the last ~20 attempts per
   * webhook (see ``Webhook.recent_deliveries``). This page renders that
   * window with per-row status badges and a per-row Retry button for
   * failed entries. The list polls every 10s; polling pauses when the
   * tab loses focus so a backgrounded dashboard doesn't hammer the API.
   *
   * Route-vs-drawer: we picked a dedicated route over a drawer so the
   * URL is shareable when paging an admin into a misbehaving hook
   * ("here's the failing webhook → /webhooks/<id>/deliveries"). The
   * trade-off is one extra click compared to a sheet, but the surface
   * is rich enough (error messages, retry, expand details) that it
   * benefits from the full page width and back/forward semantics.
   */

  import {
    ArrowLeft,
    Loader2,
    Pause,
    Play,
    RefreshCcw,
    RotateCcw,
    Send,
    ShieldCheck,
  } from '@lucide/svelte';
  import { resolve } from '$app/paths';
  import { Badge } from '$lib/components/ui/badge';
  import { Button } from '$lib/components/ui/button';
  import { Card, CardContent, CardHeader, CardTitle } from '$lib/components/ui/card';
  import RelativeTime from '$lib/components/app/RelativeTime.svelte';
  import {
    createWebhooksQuery,
    createWebhookDeliveriesQuery,
    createRetryDeliveryMutation,
    createTestWebhookMutation,
  } from '$lib/queries';
  import { userStore } from '$lib/stores/user.svelte';
  import type { WebhookDeliveryEntry, WebhookSummary } from '$lib/api';

  type Data = { webhookId: string };
  const { data }: { data: Data } = $props();

  const isAdmin = $derived(userStore.value?.user_role === 'admin');

  // ---- Auto-refresh toggle ----
  let autoRefresh = $state(true);

  // Pause polling when the tab is hidden — Page Visibility API. The
  // svelte-query layer respects ``enabled`` so toggling this is enough.
  let tabVisible = $state(typeof document === 'undefined' ? true : !document.hidden);
  $effect(() => {
    if (typeof document === 'undefined') return;
    const onVis = () => (tabVisible = !document.hidden);
    document.addEventListener('visibilitychange', onVis);
    return () => document.removeEventListener('visibilitychange', onVis);
  });

  // Read once via a closure to avoid svelte-check's "state captured
  // locally" warning. The route param can't change without the
  // component remounting via SvelteKit, so this is effectively
  // const-after-mount.
  const webhookId = (() => data.webhookId)();

  // ---- Data ----
  // We piggyback on the list query for the webhook metadata (name, url,
  // failure_count etc.) so we don't add a `/v1/dash/webhooks/{id}` round
  // trip — the list is already in cache after a visit to /webhooks.
  const webhooksQuery = createWebhooksQuery();
  const hook = $derived<WebhookSummary | undefined>(
    $webhooksQuery.data?.webhooks.find((w) => w.id === webhookId),
  );

  // svelte-query reads ``refetchInterval`` via a function callback so it
  // can re-evaluate "should I poll right now?" on every tick — we route
  // it through this closure so the rune values stay live.
  const deliveriesQuery = createWebhookDeliveriesQuery(webhookId, {
    intervalMs: 10_000,
    shouldPoll: () => autoRefresh && tabVisible,
    enabled: userStore.value?.user_role === 'admin',
  });
  const retryMut = createRetryDeliveryMutation(webhookId);
  const testMut = createTestWebhookMutation();

  // ---- Derived UI helpers ----
  function statusBadge(d: WebhookDeliveryEntry): {
    variant: 'success' | 'default' | 'warn' | 'danger' | 'muted';
    label: string;
  } {
    if (d.status_code == null) {
      // No status_code on a failed attempt = network/timeout.
      return { variant: 'muted', label: d.error ? 'timeout' : 'pending' };
    }
    const s = d.status_code;
    if (s >= 200 && s < 300) return { variant: 'success', label: `${s}` };
    if (s >= 300 && s < 400) return { variant: 'default', label: `${s}` };
    if (s >= 400 && s < 500) return { variant: 'warn', label: `${s}` };
    return { variant: 'danger', label: `${s}` };
  }

  function isFailed(d: WebhookDeliveryEntry): boolean {
    return !d.success;
  }

  // Track which rows have their error message expanded.
  let expanded = $state<Record<string, boolean>>({});

  function toggleExpand(id: string): void {
    expanded[id] = !expanded[id];
  }

  async function onRetry(d: WebhookDeliveryEntry): Promise<void> {
    try {
      await $retryMut.mutateAsync(d.delivery_id);
    } catch {
      /* surfaced by mutation toast */
    }
  }

  async function onTest(): Promise<void> {
    if (!hook) return;
    try {
      await $testMut.mutateAsync(hook.id);
    } catch {
      /* surfaced by mutation toast */
    }
  }

  function manualRefresh(): void {
    void $deliveriesQuery.refetch();
  }

  const deliveries = $derived<WebhookDeliveryEntry[]>($deliveriesQuery.data?.deliveries ?? []);
</script>

<svelte:head>
  <title>{hook ? `${hook.name} — Deliveries` : 'Webhook deliveries'} — Remote-Pulse</title>
</svelte:head>

<section
  class="mx-auto w-full max-w-7xl space-y-6 px-4 py-6 sm:px-6"
  data-testid="webhook-deliveries-page"
>
  <!-- ============ Breadcrumb + header ============ -->
  <nav class="text-sm text-muted" aria-label="Breadcrumb">
    <a
      href={resolve('/webhooks')}
      class="inline-flex items-center gap-1 hover:text-default hover:underline"
      data-testid="deliveries-back-link"
    >
      <ArrowLeft class="size-3.5" aria-hidden="true" />
      Webhooks
    </a>
    <span class="mx-2 text-muted/60">/</span>
    <span class="text-default">{hook?.name ?? 'Loading…'}</span>
    <span class="mx-2 text-muted/60">/</span>
    <span>Deliveries</span>
  </nav>

  <header class="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
    <div class="min-w-0">
      <h1 class="truncate text-2xl font-semibold tracking-tight">
        {hook?.name ?? 'Webhook'}
      </h1>
      {#if hook}
        <p class="mt-1 break-all text-xs text-muted">
          <code>{hook.url}</code>
        </p>
        <p class="mt-1 text-sm text-muted">
          Showing the last {$deliveriesQuery.data?.max_history ?? 20} delivery attempts.
          {#if hook.failure_count >= 10}
            <Badge variant="danger" class="ml-2">Auto-disabled</Badge>
          {:else if hook.failure_count > 0}
            <span class="ml-2 text-danger-text"
              >({hook.failure_count} consecutive failure{hook.failure_count === 1 ? '' : 's'})</span
            >
          {/if}
        </p>
      {/if}
    </div>
    {#if isAdmin}
      <div class="flex flex-wrap items-center gap-2">
        <Button
          variant="ghost"
          size="sm"
          onclick={() => (autoRefresh = !autoRefresh)}
          aria-pressed={autoRefresh}
          data-testid="deliveries-autorefresh-btn"
          title={autoRefresh ? 'Pause auto-refresh' : 'Resume auto-refresh'}
        >
          {#if autoRefresh}
            <Pause class="mr-1 size-4" aria-hidden="true" />
            Auto-refresh on
          {:else}
            <Play class="mr-1 size-4" aria-hidden="true" />
            Auto-refresh off
          {/if}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onclick={manualRefresh}
          disabled={$deliveriesQuery.isFetching}
          data-testid="deliveries-refresh-btn"
        >
          {#if $deliveriesQuery.isFetching}
            <Loader2 class="mr-1 size-4 animate-spin" aria-hidden="true" />
          {:else}
            <RefreshCcw class="mr-1 size-4" aria-hidden="true" />
          {/if}
          Refresh
        </Button>
        <Button
          variant="default"
          size="sm"
          onclick={onTest}
          disabled={!hook || $testMut.isPending}
          data-testid="deliveries-test-btn"
        >
          <Send class="mr-1 size-4" aria-hidden="true" />
          Test
        </Button>
      </div>
    {/if}
  </header>

  <!-- ============ Body ============ -->
  {#if !isAdmin}
    <Card>
      <CardContent class="py-8 text-center text-sm text-muted">
        <ShieldCheck class="mx-auto mb-2 size-6" aria-hidden="true" />
        Webhooks are admin-only.
      </CardContent>
    </Card>
  {:else if $deliveriesQuery.isPending}
    <Card>
      <CardContent class="flex items-center justify-center gap-2 py-12 text-sm text-muted">
        <Loader2 class="size-4 animate-spin" aria-hidden="true" />
        Loading deliveries…
      </CardContent>
    </Card>
  {:else if $deliveriesQuery.isError}
    <Card>
      <CardContent class="py-8 text-center text-sm text-danger-text">
        Could not load deliveries: {$deliveriesQuery.error?.message ?? 'Unknown error'}
      </CardContent>
    </Card>
  {:else if deliveries.length === 0}
    <Card>
      <CardContent class="py-12 text-center text-sm text-muted">
        No deliveries yet. Click <strong>Test</strong> to fire a synthetic <code>webhook.test</code>
        event.
      </CardContent>
    </Card>
  {:else}
    <Card>
      <CardHeader>
        <CardTitle>Delivery log</CardTitle>
      </CardHeader>
      <CardContent class="overflow-x-auto p-0">
        <table class="w-full min-w-[900px] text-sm">
          <thead
            class="border-b border-border-subtle bg-subtle/30 text-left text-xs uppercase tracking-wide text-muted"
          >
            <tr>
              <th class="px-4 py-2">Time</th>
              <th class="px-4 py-2">Event</th>
              <th class="px-4 py-2">Status</th>
              <th class="px-4 py-2">Attempt</th>
              <th class="px-4 py-2">Delivery ID</th>
              <th class="px-4 py-2">Error</th>
              <th class="px-4 py-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {#each deliveries as d (d.delivery_id)}
              {@const sb = statusBadge(d)}
              {@const failed = isFailed(d)}
              {@const isExpanded = Boolean(expanded[d.delivery_id])}
              <tr
                class="border-b border-border-subtle last:border-0"
                data-testid="delivery-row"
                data-delivery-id={d.delivery_id}
                data-success={d.success ? 'true' : 'false'}
              >
                <td class="px-4 py-2 text-xs text-muted">
                  <RelativeTime iso={d.timestamp} />
                </td>
                <td class="px-4 py-2">
                  <code class="text-xs">{d.event}</code>
                  {#if d.retry_of}
                    <Badge variant="secondary" class="ml-1" title="Manual retry of {d.retry_of}">
                      retry
                    </Badge>
                  {/if}
                </td>
                <td class="px-4 py-2">
                  <Badge variant={sb.variant} data-testid="delivery-status-badge">
                    {sb.label}
                  </Badge>
                </td>
                <td class="px-4 py-2 text-xs text-muted">
                  {d.attempt}/4
                  {#if d.attempt >= 4 && !d.success}
                    <span class="ml-1 text-danger-text" title="All retries exhausted">⚠</span>
                  {/if}
                </td>
                <td class="px-4 py-2">
                  <code class="break-all font-mono text-[10px] text-muted" title={d.delivery_id}
                    >{d.delivery_id.slice(0, 8)}…</code
                  >
                </td>
                <td class="px-4 py-2 text-xs">
                  {#if d.error}
                    {#if isExpanded}
                      <span class="break-all text-danger-text">{d.error}</span>
                      <button
                        type="button"
                        class="ml-1 text-accent underline"
                        onclick={() => toggleExpand(d.delivery_id)}
                        data-testid="delivery-error-collapse"
                      >
                        less
                      </button>
                    {:else}
                      <span class="text-danger-text">
                        {d.error.length > 60 ? `${d.error.slice(0, 60)}…` : d.error}
                      </span>
                      {#if d.error.length > 60}
                        <button
                          type="button"
                          class="ml-1 text-accent underline"
                          onclick={() => toggleExpand(d.delivery_id)}
                          data-testid="delivery-error-expand"
                        >
                          View full
                        </button>
                      {/if}
                    {/if}
                  {:else}
                    <span class="text-muted">—</span>
                  {/if}
                </td>
                <td class="px-4 py-2">
                  <div class="flex items-center justify-end gap-1">
                    {#if failed}
                      <Button
                        variant="ghost"
                        size="sm"
                        onclick={() => onRetry(d)}
                        disabled={$retryMut.isPending}
                        data-testid="delivery-retry-btn"
                        aria-label={`Retry delivery ${d.delivery_id}`}
                      >
                        {#if $retryMut.isPending && $retryMut.variables === d.delivery_id}
                          <Loader2 class="size-4 animate-spin" aria-hidden="true" />
                        {:else}
                          <RotateCcw class="size-4" aria-hidden="true" />
                        {/if}
                      </Button>
                    {:else}
                      <span class="text-xs text-muted">—</span>
                    {/if}
                  </div>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </CardContent>
    </Card>
  {/if}
</section>
