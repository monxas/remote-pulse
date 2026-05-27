<script lang="ts">
  /**
   * Audit log retention configuration card.
   *
   * Renders inside Settings → Retention (admin-only). Three controls:
   *  - A number input for "retain N days" (bounded by min_days/max_days
   *    from the server, so the client never disagrees with the policy).
   *  - A toggle for the background purge loop (``enabled``).
   *  - A "Purge now" button gated behind a confirmation dialog — the
   *    deletion is irreversible so a single misclick should not eat
   *    audit history.
   *
   * Status line surfaces ``last_purge_at`` + ``last_purge_count`` so an
   * admin can confirm the loop is alive without leaving the page. We
   * format the timestamp as a relative string (``2 hours ago``) because
   * the absolute ts is rarely what an operator wants — they care that
   * it ran *recently*, not the exact wall-clock instant.
   */
  import { Loader2, RotateCcw, Trash2, Clock } from '@lucide/svelte';
  import { Badge } from '$lib/components/ui/badge';
  import { Button } from '$lib/components/ui/button';
  import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogDescription,
    DialogFooter,
  } from '$lib/components/ui/dialog';
  import {
    createRetentionQuery,
    createUpdateRetentionMutation,
    createPurgeRetentionMutation,
  } from '$lib/queries';
  import { formatRelativeTime } from './retention-format';

  const retentionQuery = createRetentionQuery();
  const updateMutation = createUpdateRetentionMutation();
  const purgeMutation = createPurgeRetentionMutation();

  const config = $derived($retentionQuery.data);

  // Local-edited copies so the input doesn't fight the server while
  // the user is typing. Synced from the query when it arrives, and
  // also after a mutation settles (via invalidation).
  let editDays = $state<number>(90);
  let editEnabled = $state<boolean>(true);

  // Sync local state once the query resolves and any time the server
  // payload changes (e.g. after a successful PATCH the query refetches).
  $effect(() => {
    if (config) {
      editDays = config.retention_days;
      editEnabled = config.enabled;
    }
  });

  const dirty = $derived(
    !!config && (editDays !== config.retention_days || editEnabled !== config.enabled),
  );

  const lastPurgeLabel = $derived(
    config?.last_purge_at ? formatRelativeTime(config.last_purge_at) : null,
  );

  let purgeConfirmOpen = $state(false);

  function saveChanges(): void {
    if (!config) return;
    const patch: { retention_days?: number; enabled?: boolean } = {};
    if (editDays !== config.retention_days) patch.retention_days = editDays;
    if (editEnabled !== config.enabled) patch.enabled = editEnabled;
    if (Object.keys(patch).length === 0) return;
    $updateMutation.mutate(patch);
  }

  function resetChanges(): void {
    if (!config) return;
    editDays = config.retention_days;
    editEnabled = config.enabled;
  }

  function openPurgeConfirm(): void {
    purgeConfirmOpen = true;
  }

  function confirmPurge(): void {
    $purgeMutation.mutate(undefined, {
      onSettled: () => {
        purgeConfirmOpen = false;
      },
    });
  }
</script>

<div class="space-y-4" data-testid="retention-card">
  {#if $retentionQuery.isPending}
    <div class="flex items-center gap-2 text-sm text-muted">
      <Loader2 class="size-4 animate-spin" aria-hidden="true" />
      Loading retention policy…
    </div>
  {:else if $retentionQuery.isError}
    <div class="space-y-2 text-sm">
      <p class="text-danger-text">
        Failed to load retention policy: {$retentionQuery.error?.message ?? 'unknown error'}
      </p>
      <Button size="sm" onclick={() => void $retentionQuery.refetch()}>Retry</Button>
    </div>
  {:else if config}
    <!-- Status banner -->
    <div
      class="flex flex-col gap-3 rounded-lg border border-border-subtle bg-subtle/40 p-4 sm:flex-row sm:items-start sm:justify-between"
      data-testid="retention-status"
    >
      <div class="flex items-start gap-3">
        <Clock class="mt-0.5 size-5 text-muted" aria-hidden="true" />
        <div class="space-y-1">
          <p class="text-sm">
            Currently retaining
            <strong data-testid="retention-current-days">{config.retention_days}</strong> days of audit
            history.
          </p>
          {#if lastPurgeLabel && config.last_purge_count !== null}
            <p class="text-xs text-muted" data-testid="retention-last-purge">
              Last purge: {lastPurgeLabel} (deleted {config.last_purge_count}
              event{config.last_purge_count === 1 ? '' : 's'}).
            </p>
          {:else}
            <p class="text-xs text-muted" data-testid="retention-last-purge">
              No purge has run yet.
            </p>
          {/if}
        </div>
      </div>
      <Badge variant={config.enabled ? 'default' : 'muted'} class="self-start">
        {config.enabled ? 'Auto-purge enabled' : 'Auto-purge paused'}
      </Badge>
    </div>

    <!-- Controls -->
    <div class="space-y-4">
      <label class="block text-sm">
        <span class="mb-1 block font-medium">Retain for (days)</span>
        <div class="flex items-center gap-3">
          <input
            type="number"
            min={config.min_days}
            max={config.max_days}
            bind:value={editDays}
            data-testid="retention-days-input"
            class="flex h-9 w-32 rounded-md border border-border-default bg-base px-3 py-1 text-sm text-default shadow-sm focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          />
          <input
            type="range"
            min={config.min_days}
            max={config.max_days}
            bind:value={editDays}
            class="flex-1 accent-[var(--accent-solid)]"
            aria-label="Retention days slider"
            data-testid="retention-days-slider"
          />
        </div>
        <span class="mt-1 block text-xs text-muted">
          Between {config.min_days} and {config.max_days} days. Default 90.
        </span>
      </label>

      <label class="flex cursor-pointer items-center gap-2 text-sm">
        <input
          type="checkbox"
          class="size-4 cursor-pointer accent-[var(--accent-solid)]"
          bind:checked={editEnabled}
          data-testid="retention-enabled-toggle"
        />
        <span>Enable automatic daily purge</span>
      </label>
    </div>

    <!-- Action bar -->
    <div
      class="flex flex-col gap-2 border-t border-border-subtle pt-3 sm:flex-row sm:items-center sm:justify-between"
    >
      <div class="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          disabled={!dirty || $updateMutation.isPending}
          onclick={saveChanges}
          data-testid="retention-save"
        >
          {#if $updateMutation.isPending}
            <Loader2 class="mr-1 size-4 animate-spin" aria-hidden="true" />
          {/if}
          Save changes
        </Button>
        <Button
          size="sm"
          variant="ghost"
          disabled={!dirty || $updateMutation.isPending}
          onclick={resetChanges}
          data-testid="retention-reset"
        >
          <RotateCcw class="mr-1 size-4" aria-hidden="true" />
          Reset
        </Button>
      </div>
      <Button
        size="sm"
        variant="danger"
        onclick={openPurgeConfirm}
        disabled={$purgeMutation.isPending}
        data-testid="retention-purge-now"
      >
        <Trash2 class="mr-1 size-4" aria-hidden="true" />
        Purge now
      </Button>
    </div>
  {/if}
</div>

<!-- Confirmation modal. Deletion is irreversible so we gate it. -->
<Dialog bind:open={purgeConfirmOpen} onOpenChange={(o) => (purgeConfirmOpen = o)}>
  <DialogContent>
    <DialogHeader>
      <DialogTitle>Purge audit events now?</DialogTitle>
      <DialogDescription>
        This deletes every <code>audit_events</code> row older than
        {config?.retention_days ?? '?'} days. The deletion cannot be undone.
      </DialogDescription>
    </DialogHeader>
    <DialogFooter>
      <Button
        type="button"
        variant="ghost"
        onclick={() => (purgeConfirmOpen = false)}
        disabled={$purgeMutation.isPending}
      >
        Cancel
      </Button>
      <Button
        type="button"
        variant="danger"
        onclick={confirmPurge}
        disabled={$purgeMutation.isPending}
        data-testid="retention-purge-confirm"
      >
        {#if $purgeMutation.isPending}
          <Loader2 class="mr-1 size-4 animate-spin" aria-hidden="true" />
        {/if}
        Yes, purge now
      </Button>
    </DialogFooter>
  </DialogContent>
</Dialog>
