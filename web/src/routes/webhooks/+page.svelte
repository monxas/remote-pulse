<script lang="ts">
  /**
   * Webhooks admin page.
   *
   * Lets admins register outbound webhook subscriptions: external URL +
   * event filter + optional group filter. The secret returned on create
   * is the ONLY chance to grab it (server never re-emits it), so the
   * post-create dialog double-down on that with a copy button and a big
   * warning. Toggling `enabled` and firing a synthetic test event is
   * available per row.
   */

  import {
    Copy,
    History,
    Loader2,
    Plus,
    RotateCcw,
    Send,
    ShieldCheck,
    Trash2,
    TriangleAlert,
  } from '@lucide/svelte';
  import { toast } from 'svelte-sonner';
  import { resolve } from '$app/paths';
  import { Badge } from '$lib/components/ui/badge';
  import { Button } from '$lib/components/ui/button';
  import { Card, CardContent, CardHeader, CardTitle } from '$lib/components/ui/card';
  import { Input } from '$lib/components/ui/input';
  import { Switch } from '$lib/components/ui/switch';
  import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
  } from '$lib/components/ui/dialog';
  import {
    createWebhooksQuery,
    createCreateWebhookMutation,
    createDeleteWebhookMutation,
    createResetFailuresMutation,
    createSettingsGroupsQuery,
    createTestWebhookMutation,
    createUpdateWebhookMutation,
  } from '$lib/queries';
  // ``AUTO_DISABLE_AFTER`` on the server. Mirrored here so the UI can
  // surface "Auto-disabled" without a round trip — kept in sync via the
  // backend's documented threshold (see rp_server.webhooks).
  const AUTO_DISABLE_AFTER = 10;
  import { userStore } from '$lib/stores/user.svelte';
  import type { CreateWebhookInput, WebhookCreateResponse, WebhookSummary } from '$lib/api';

  // ---- Data + mutations ----
  const webhooksQuery = createWebhooksQuery();
  const groupsQuery = createSettingsGroupsQuery();
  const createMut = createCreateWebhookMutation();
  const updateMut = createUpdateWebhookMutation();
  const deleteMut = createDeleteWebhookMutation();
  const testMut = createTestWebhookMutation();
  const resetFailuresMut = createResetFailuresMutation();

  const webhooks = $derived<WebhookSummary[]>($webhooksQuery.data?.webhooks ?? []);
  // Sorted group names available as filter pills. We read from the live
  // /v1/dash/settings/groups list so the operator can only pick groups
  // that exist — no typos, no stale references.
  const availableGroups = $derived(
    ($groupsQuery.data?.groups ?? [])
      .map((g) => g.name)
      .filter((n) => typeof n === 'string')
      .sort(),
  );

  // ---- New webhook modal state ----
  let createOpen = $state(false);
  let newName = $state('');
  let newUrl = $state('');
  // Pre-populate the most useful presets so the empty-form is one click
  // away from "all events" for the common n8n / Discord use case.
  const EVENT_PRESETS = [
    { key: '*', label: 'All events' },
    { key: 'command.', label: 'Commands' },
    { key: 'host.', label: 'Hosts' },
    { key: 'approval.', label: 'Approvals' },
    { key: 'settings.', label: 'Settings' },
    { key: 'audit.', label: 'Audit' },
  ] as const;
  let newEventFilter = $state<string[]>(['*']);
  // Multi-select pills (v1.0.14): pick from /v1/dash/settings/groups
  // instead of free-text. Empty array = no filter (delivery on every group).
  let newGroupFilter = $state<string[]>([]);

  function toggleGroup(name: string): void {
    newGroupFilter = newGroupFilter.includes(name)
      ? newGroupFilter.filter((g) => g !== name)
      : [...newGroupFilter, name];
  }

  function toggleEvent(key: string): void {
    if (key === '*') {
      newEventFilter = ['*'];
      return;
    }
    // Selecting any specific filter implicitly removes the wildcard.
    const next = newEventFilter.filter((e) => e !== '*');
    if (next.includes(key)) {
      newEventFilter = next.filter((e) => e !== key);
    } else {
      newEventFilter = [...next, key];
    }
    if (newEventFilter.length === 0) newEventFilter = ['*'];
  }

  function resetNewForm(): void {
    newName = '';
    newUrl = '';
    newEventFilter = ['*'];
    newGroupFilter = [];
  }

  // ---- Secret-just-once dialog state ----
  let revealOpen = $state(false);
  let revealed = $state<WebhookCreateResponse | null>(null);

  async function copyToClipboard(text: string, label = 'Copied'): Promise<void> {
    try {
      await navigator.clipboard.writeText(text);
      toast.success(label);
    } catch (err) {
      toast.error('Clipboard unavailable', {
        description: err instanceof Error ? err.message : String(err),
      });
    }
  }

  async function submitNew(e: Event): Promise<void> {
    e.preventDefault();
    if (!newName.trim() || !newUrl.trim()) {
      toast.error('Name and URL are required');
      return;
    }
    const input: CreateWebhookInput = {
      name: newName.trim(),
      url: newUrl.trim(),
      event_filter: newEventFilter,
      group_filter: newGroupFilter.length > 0 ? newGroupFilter : null,
    };
    try {
      const out = await $createMut.mutateAsync(input);
      createOpen = false;
      resetNewForm();
      revealed = out;
      revealOpen = true;
    } catch {
      /* toast already surfaced by the mutation */
    }
  }

  async function toggleEnabled(hook: WebhookSummary, next: boolean): Promise<void> {
    try {
      await $updateMut.mutateAsync({ id: hook.id, input: { enabled: next } });
    } catch {
      /* surfaced by toast */
    }
  }

  async function deleteHook(hook: WebhookSummary): Promise<void> {
    // `window.confirm` is the same destructive-action UX used by the
    // enroll page; we deliberately stay consistent rather than introduce
    // an extra confirmation modal for what is a per-row destructive.
    if (
      !window.confirm(
        `Delete webhook "${hook.name}"? This cannot be undone. The receiver at ${hook.url} will stop getting events.`,
      )
    )
      return;
    try {
      await $deleteMut.mutateAsync(hook.id);
    } catch {
      /* surfaced by toast */
    }
  }

  async function testHook(hook: WebhookSummary): Promise<void> {
    try {
      await $testMut.mutateAsync(hook.id);
    } catch {
      /* surfaced by toast */
    }
  }

  async function resetFailures(hook: WebhookSummary): Promise<void> {
    // Cheap-and-cheerful confirm — same pattern as `deleteHook`. The
    // intent here is "I fixed the receiver, lift the auto-disable",
    // so we don't gate behind a full modal.
    if (
      !window.confirm(
        `Reset failures for "${hook.name}"? This clears the consecutive-failure counter and re-enables the webhook.`,
      )
    )
      return;
    try {
      await $resetFailuresMut.mutateAsync(hook.id);
    } catch {
      /* surfaced by toast */
    }
  }

  function isAutoDisabled(hook: WebhookSummary): boolean {
    // Server flips ``enabled = false`` once ``failure_count`` hits the
    // threshold, so the row's auto-disabled iff both conditions hold.
    // (A hook that's disabled manually with failure_count < threshold is
    // intentionally NOT shown as auto-disabled.)
    return !hook.enabled && hook.failure_count >= AUTO_DISABLE_AFTER;
  }

  function statusBadge(hook: WebhookSummary) {
    if (!hook.enabled) return { variant: 'muted' as const, label: 'disabled' };
    if (hook.last_status_code == null) return { variant: 'secondary' as const, label: 'idle' };
    if (hook.last_status_code >= 200 && hook.last_status_code < 300)
      return { variant: 'success' as const, label: `${hook.last_status_code} ok` };
    return { variant: 'danger' as const, label: `${hook.last_status_code} fail` };
  }

  function fmtTimestamp(iso: string | null): string {
    if (!iso) return '—';
    try {
      const d = new Date(iso);
      return d.toLocaleString();
    } catch {
      return iso;
    }
  }

  const isAdmin = $derived(userStore.value?.user_role === 'admin');
</script>

<svelte:head>
  <title>Webhooks — Remote-Pulse</title>
</svelte:head>

<section class="mx-auto w-full max-w-7xl space-y-6 px-4 py-6 sm:px-6" data-testid="webhooks-page">
  <header class="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
    <div>
      <h1 class="text-2xl font-semibold tracking-tight">Webhooks</h1>
      <p class="mt-1 text-sm text-muted">
        Forward Remote-Pulse events to external URLs. Each delivery is signed with HMAC-SHA256 so
        the receiver can verify authenticity. Useful for n8n, Discord, Slack, or any HTTP target.
      </p>
    </div>
    {#if isAdmin}
      <Button onclick={() => (createOpen = true)} data-testid="webhooks-new-btn">
        <Plus class="mr-1 size-4" aria-hidden="true" />
        New webhook
      </Button>
    {/if}
  </header>

  {#if !isAdmin}
    <Card>
      <CardContent class="py-8 text-center text-sm text-muted">
        <ShieldCheck class="mx-auto mb-2 size-6" aria-hidden="true" />
        Webhooks are admin-only.
      </CardContent>
    </Card>
  {:else if $webhooksQuery.isPending}
    <Card>
      <CardContent class="flex items-center justify-center gap-2 py-12 text-sm text-muted">
        <Loader2 class="size-4 animate-spin" aria-hidden="true" />
        Loading webhooks…
      </CardContent>
    </Card>
  {:else if $webhooksQuery.isError}
    <Card>
      <CardContent class="py-8 text-center text-sm text-danger-text">
        Could not load webhooks: {$webhooksQuery.error?.message ?? 'Unknown error'}
      </CardContent>
    </Card>
  {:else if webhooks.length === 0}
    <Card>
      <CardContent class="py-12 text-center text-sm text-muted">
        No webhooks yet. Click <strong>New webhook</strong> to forward events to an external URL.
      </CardContent>
    </Card>
  {:else}
    <Card>
      <CardHeader>
        <CardTitle>Registered webhooks</CardTitle>
      </CardHeader>
      <CardContent class="overflow-x-auto p-0">
        <table class="w-full min-w-[800px] text-sm">
          <thead
            class="border-b border-border-subtle bg-subtle/30 text-left text-xs uppercase tracking-wide text-muted"
          >
            <tr>
              <th class="px-4 py-2">Name</th>
              <th class="px-4 py-2">URL</th>
              <th class="px-4 py-2">Events</th>
              <th class="px-4 py-2">Enabled</th>
              <th class="px-4 py-2">Last fired</th>
              <th class="px-4 py-2">Last status</th>
              <th class="px-4 py-2">Failures</th>
              <th class="px-4 py-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {#each webhooks as hook (hook.id)}
              {@const sb = statusBadge(hook)}
              <tr
                class="border-b border-border-subtle last:border-0"
                data-testid="webhook-row"
                data-webhook-id={hook.id}
              >
                <td class="px-4 py-2 font-medium">{hook.name}</td>
                <td class="px-4 py-2">
                  <code class="break-all text-xs text-muted">{hook.url}</code>
                </td>
                <td class="px-4 py-2">
                  <div class="flex flex-wrap gap-1">
                    {#each hook.event_filter as evt}
                      <Badge variant="outline">{evt}</Badge>
                    {/each}
                    {#if hook.group_filter && hook.group_filter.length > 0}
                      <Badge variant="secondary">
                        groups: {hook.group_filter.join(', ')}
                      </Badge>
                    {/if}
                  </div>
                </td>
                <td class="px-4 py-2">
                  <Switch
                    checked={hook.enabled}
                    onCheckedChange={(v: boolean) => toggleEnabled(hook, v)}
                    aria-label={`Enable webhook ${hook.name}`}
                  />
                </td>
                <td class="px-4 py-2 text-xs text-muted">{fmtTimestamp(hook.last_fired_at)}</td>
                <td class="px-4 py-2">
                  <Badge variant={sb.variant}>{sb.label}</Badge>
                </td>
                <td class="px-4 py-2">
                  {#if isAutoDisabled(hook)}
                    <Badge
                      variant="danger"
                      data-testid="webhook-autodisabled-badge"
                      title="Disabled after {AUTO_DISABLE_AFTER} consecutive failures. Re-enable manually after fixing."
                    >
                      Auto-disabled ({hook.failure_count})
                    </Badge>
                  {:else if hook.failure_count > 0}
                    <span class="text-danger-text">{hook.failure_count}</span>
                  {:else}
                    <span class="text-muted">0</span>
                  {/if}
                </td>
                <td class="px-4 py-2">
                  <div class="flex items-center justify-end gap-1">
                    <a
                      href={resolve('/webhooks/[id]/deliveries', { id: hook.id })}
                      class="inline-flex h-8 items-center justify-center rounded-md px-2 text-sm hover:bg-subtle"
                      data-testid="webhook-deliveries-link"
                      aria-label={`View deliveries for ${hook.name}`}
                      title="View deliveries"
                    >
                      <History class="size-4" aria-hidden="true" />
                    </a>
                    <Button
                      variant="ghost"
                      size="sm"
                      onclick={() => testHook(hook)}
                      data-testid="webhook-test-btn"
                      aria-label={`Test webhook ${hook.name}`}
                    >
                      <Send class="size-4" aria-hidden="true" />
                    </Button>
                    {#if hook.failure_count > 0}
                      <Button
                        variant="ghost"
                        size="sm"
                        onclick={() => resetFailures(hook)}
                        disabled={$resetFailuresMut.isPending}
                        data-testid="webhook-reset-failures-btn"
                        aria-label={`Reset failures for ${hook.name}`}
                        title="Reset failure counter and re-enable"
                      >
                        <RotateCcw class="size-4" aria-hidden="true" />
                      </Button>
                    {/if}
                    <Button
                      variant="ghost"
                      size="sm"
                      onclick={() => deleteHook(hook)}
                      data-testid="webhook-delete-btn"
                      aria-label={`Delete webhook ${hook.name}`}
                    >
                      <Trash2 class="size-4 text-danger-text" aria-hidden="true" />
                    </Button>
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

<!-- ====================== Dialog: New webhook ====================== -->
<Dialog bind:open={createOpen} onOpenChange={(o) => (createOpen = o)}>
  <DialogContent>
    <form onsubmit={submitNew}>
      <DialogHeader>
        <DialogTitle>New webhook</DialogTitle>
        <DialogDescription>
          Pick which events to forward and where. The HMAC secret will be shown
          <strong>once</strong> after creation — save it immediately, you cannot retrieve it later.
        </DialogDescription>
      </DialogHeader>
      <div class="space-y-3 py-4">
        <label class="block text-sm">
          <span class="mb-1 block font-medium">Name</span>
          <Input bind:value={newName} placeholder="n8n bridge" required data-testid="wh-name" />
        </label>
        <label class="block text-sm">
          <span class="mb-1 block font-medium">URL</span>
          <Input
            bind:value={newUrl}
            placeholder="https://n8n.example/webhook/rp"
            required
            type="url"
            data-testid="wh-url"
          />
          <span class="mt-1 block text-xs text-muted">
            HTTPS required (or HTTP to localhost / RFC1918 LAN).
          </span>
        </label>
        <div class="block text-sm">
          <span class="mb-1 block font-medium">Events</span>
          <div class="flex flex-wrap gap-1" data-testid="wh-events">
            {#each EVENT_PRESETS as preset (preset.key)}
              {@const on = newEventFilter.includes(preset.key)}
              <button
                type="button"
                class={`rounded-full border px-2 py-0.5 text-xs transition-colors ${
                  on
                    ? 'border-accent bg-accent/10 text-accent'
                    : 'border-border-default text-muted hover:bg-subtle'
                }`}
                onclick={() => toggleEvent(preset.key)}
                aria-pressed={on}
              >
                {preset.label}
              </button>
            {/each}
          </div>
        </div>
        <div class="block text-sm">
          <span class="mb-1 block font-medium">Group filter (optional)</span>
          {#if availableGroups.length === 0}
            <p class="text-xs text-muted" data-testid="wh-groups-empty">
              No groups in the system yet. Leave blank to deliver every event.
            </p>
          {:else}
            <div class="flex flex-wrap gap-1" data-testid="wh-groups">
              {#each availableGroups as g (g)}
                {@const on = newGroupFilter.includes(g)}
                <button
                  type="button"
                  class={`rounded-full border px-2 py-0.5 text-xs transition-colors ${
                    on
                      ? 'border-accent bg-accent/10 text-accent'
                      : 'border-border-default text-muted hover:bg-subtle'
                  }`}
                  onclick={() => toggleGroup(g)}
                  aria-pressed={on}
                  data-testid={`wh-group-${g}`}
                >
                  {g}
                </button>
              {/each}
            </div>
          {/if}
          <span class="mt-1 block text-xs text-muted">
            {newGroupFilter.length === 0
              ? 'Leave none selected to receive events from every group.'
              : `Delivering only for: ${newGroupFilter.join(', ')}`}
          </span>
        </div>
      </div>
      <DialogFooter>
        <Button type="button" variant="ghost" onclick={() => (createOpen = false)}>Cancel</Button>
        <Button
          type="submit"
          disabled={$createMut.isPending || !newName.trim() || !newUrl.trim()}
          data-testid="wh-create-submit"
        >
          {#if $createMut.isPending}
            <Loader2 class="mr-1 size-4 animate-spin" aria-hidden="true" />
          {/if}
          Create webhook
        </Button>
      </DialogFooter>
    </form>
  </DialogContent>
</Dialog>

<!-- ====================== Dialog: Secret reveal (one-time) ====================== -->
<Dialog bind:open={revealOpen} onOpenChange={(o) => (revealOpen = o)}>
  <DialogContent>
    <DialogHeader>
      <DialogTitle class="flex items-center gap-2">
        <TriangleAlert class="size-5 text-warn-text" aria-hidden="true" />
        Save your webhook secret
      </DialogTitle>
      <DialogDescription>
        This is the only time you'll see this secret. Copy it now and store it on the receiver side
        — Remote-Pulse cannot retrieve it later. The receiver verifies each delivery's
        <code class="rounded bg-subtle px-1">X-RP-Signature-256</code> header with this secret.
      </DialogDescription>
    </DialogHeader>
    {#if revealed}
      <div class="space-y-3 py-4">
        <div class="block text-sm">
          <span class="mb-1 block font-medium">Webhook</span>
          <code class="break-all text-xs text-muted" data-testid="wh-revealed-name"
            >{revealed.name}</code
          >
        </div>
        <div class="block text-sm">
          <span class="mb-1 block font-medium">Secret</span>
          <div class="flex items-center gap-2">
            <code
              class="flex-1 break-all rounded border border-border-default bg-subtle px-2 py-1.5 font-mono text-xs"
              data-testid="wh-revealed-secret"
            >
              {revealed.secret}
            </code>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onclick={() => revealed && copyToClipboard(revealed.secret, 'Secret copied')}
              data-testid="wh-copy-secret"
              aria-label="Copy secret"
            >
              <Copy class="size-4" aria-hidden="true" />
            </Button>
          </div>
        </div>
      </div>
    {/if}
    <DialogFooter>
      <Button type="button" onclick={() => (revealOpen = false)}>I have saved the secret</Button>
    </DialogFooter>
  </DialogContent>
</Dialog>
