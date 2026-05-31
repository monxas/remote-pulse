<script lang="ts">
  import {
    ArrowLeft,
    ArrowRight,
    Ban,
    Check,
    Loader2,
    Terminal,
    X,
    AlertCircle,
    MinusCircle,
  } from '@lucide/svelte';
  import { useQueryClient } from '@tanstack/svelte-query';
  import { toast } from 'svelte-sonner';
  import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogDescription,
    DialogFooter,
  } from '$lib/components/ui/dialog';
  import { Button } from '$lib/components/ui/button';
  import { Input } from '$lib/components/ui/input';
  import { Textarea } from '$lib/components/ui/textarea';
  import { Switch } from '$lib/components/ui/switch';
  import { Badge } from '$lib/components/ui/badge';
  import { cn } from '$lib/utils';
  import { qk } from '$lib/queries';
  import {
    COMMAND_TYPES,
    DEFAULT_FORM_STATE,
    buildPayload,
    isPayloadValid,
    summarizePayload,
    type CommandFormState,
    type CommandTypeId,
  } from '$lib/commands/types';
  import { dispatchBulk, seedItems, type BulkItem } from '$lib/commands/bulk-dispatch';

  /**
   * Bulk variant of `IssueCommandDialog`. Designed for the Fleet table's
   * "Issue command on N selected hosts" affordance.
   *
   * Key differences from the single/multi variant we have today:
   *
   *   - Host selection is FROZEN — the caller passes `hostIds` (already
   *     chosen via the Fleet table checkboxes), so the dialog skips the
   *     host-picker step entirely.
   *   - On submit we fan-out one POST /v1/dash/commands per host so
   *     `command.issue` permission checks (per-host on the server)
   *     surface as per-host failures rather than 4xx-ing the whole
   *     batch. See `lib/commands/bulk-dispatch.ts` for the rationale.
   *   - A 4th "Results" step replaces the success-toast-and-close flow
   *     with a per-host status table so operators can spot partial
   *     failures (e.g. forbidden on a single host).
   */

  type Step = 1 | 2 | 3 | 4;

  type Props = {
    open: boolean;
    onOpenChange: (next: boolean) => void;
    /** Hosts to fan out to. Order is preserved in the results view. */
    hostIds: ReadonlyArray<string>;
    /** Parallel array of hostnames in the same order as `hostIds`. */
    hostnamesById: ReadonlyArray<string>;
    /** Fired once `dispatchBulk` resolves so the parent can clear selection. */
    onAllSubmitted?: () => void;
  };

  let { open, onOpenChange, hostIds, hostnamesById, onAllSubmitted }: Props = $props();

  let step = $state<Step>(1);
  let chosenType = $state<CommandTypeId | null>(null);
  let formState = $state<CommandFormState>(structuredClone(DEFAULT_FORM_STATE));
  let reason = $state('');
  let requiresApproval = $state(true);
  let inlineError = $state<string | null>(null);

  // Per-host dispatch state machine: idle -> submitting -> done.
  type DispatchState = 'idle' | 'submitting' | 'done';
  let dispatchState = $state<DispatchState>('idle');
  let items = $state<BulkItem[]>([]);

  // AbortController for the bulk run. We create a fresh one per submit
  // so reopening the dialog after a cancel doesn't trip on a stale
  // already-aborted signal.
  let abortCtl = $state<AbortController | null>(null);

  const queryClient = useQueryClient();

  // Build a hostId -> hostname lookup that survives even when the
  // upstream Fleet table re-sorts (we capture the snapshot at open time).
  const hostnameLookup = $derived.by(() => {
    const map: Record<string, string> = {};
    for (let i = 0; i < hostIds.length; i += 1) {
      const id = hostIds[i];
      if (id === undefined) continue;
      map[id] = hostnamesById[i] ?? id;
    }
    return map;
  });

  function resetState(): void {
    step = 1;
    chosenType = null;
    formState = structuredClone(DEFAULT_FORM_STATE);
    reason = '';
    requiresApproval = true;
    inlineError = null;
    dispatchState = 'idle';
    items = [];
    // Abort the previous run if the dialog is reopened mid-flight —
    // otherwise the worker pool would keep firing into a closed UI.
    abortCtl?.abort();
    abortCtl = null;
  }

  /** Operator-initiated mid-flight cancel. Aborts queued items; the
   * worker pool flips them to `cancelled` as it drains, and any
   * in-flight requests are allowed to settle. */
  function cancelRemaining(): void {
    abortCtl?.abort();
  }

  // Reset whenever the dialog reopens.
  $effect(() => {
    if (open) resetState();
  });

  function choose(type: CommandTypeId): void {
    chosenType = type;
    requiresApproval = COMMAND_TYPES.find((t) => t.id === type)?.defaultRequiresApproval ?? true;
    step = 2;
  }

  function canAdvance(current: Step): boolean {
    switch (current) {
      case 1:
        return chosenType !== null && isPayloadValid(chosenType, formState);
      case 2:
        return true;
      case 3:
      case 4:
        return false;
    }
  }

  function goNext(): void {
    if (!canAdvance(step)) return;
    if (step < 4) step = (step + 1) as Step;
  }

  function goBack(): void {
    if (dispatchState === 'submitting') return;
    if (step > 1) step = (step - 1) as Step;
  }

  async function submit(): Promise<void> {
    if (!chosenType || hostIds.length === 0) return;
    inlineError = null;
    let payload: Record<string, unknown>;
    try {
      payload = buildPayload(chosenType, formState);
    } catch (err) {
      inlineError = err instanceof Error ? err.message : 'Invalid payload.';
      return;
    }

    // Move to results step with seeded "pending" rows so the user sees
    // the table immediately rather than a flash of empty space.
    items = seedItems(hostIds, hostnameLookup);
    dispatchState = 'submitting';
    step = 4;

    abortCtl = new AbortController();
    const result = await dispatchBulk(
      {
        hostIds,
        hostnamesById: hostnameLookup,
        command_type: chosenType,
        command_payload: payload,
        reason: reason.trim() || undefined,
        requires_approval: requiresApproval,
        signal: abortCtl.signal,
      },
      (next) => {
        items = items.map((i) => (i.host_id === next.host_id ? next : i));
      },
    );

    dispatchState = 'done';

    // Invalidate the same caches that the single-issue mutation does so
    // any open Commands / Approvals / Overview view refetches.
    void queryClient.invalidateQueries({ queryKey: qk.commandsAll() });
    void queryClient.invalidateQueries({ queryKey: qk.approvalsAll() });
    void queryClient.invalidateQueries({ queryKey: qk.auditAll() });
    void queryClient.invalidateQueries({ queryKey: qk.overview() });

    // Cancellation is the third axis of the summary toast: surface it
    // distinctly so operators don't think the missing rows are silent
    // failures.
    const parts: string[] = [];
    if (result.okCount > 0) parts.push(`${result.okCount} issued`);
    if (result.errorCount > 0) parts.push(`${result.errorCount} failed`);
    if (result.cancelledCount > 0) parts.push(`${result.cancelledCount} cancelled`);
    const summary = parts.join(', ') || 'No commands issued';
    if (result.errorCount === 0 && result.cancelledCount === 0 && result.okCount > 0) {
      toast.success(summary);
    } else if (result.okCount === 0 && result.cancelledCount === 0) {
      toast.error(summary);
    } else {
      toast.warning(summary);
    }

    onAllSubmitted?.();
  }

  const previewPayload = $derived.by(() => {
    if (!chosenType) return '';
    try {
      return summarizePayload(buildPayload(chosenType, formState));
    } catch {
      return '';
    }
  });

  const progress = $derived.by(() => {
    const total = items.length;
    // Cancelled rows count as settled — they're not coming back.
    const settled = items.filter(
      (i) => i.status === 'success' || i.status === 'error' || i.status === 'cancelled',
    ).length;
    return { total, settled };
  });

  const okCount = $derived(items.filter((i) => i.status === 'success').length);
  const errorCount = $derived(items.filter((i) => i.status === 'error').length);
  const cancelledCount = $derived(items.filter((i) => i.status === 'cancelled').length);
  // "Can we still cancel?" iff at least one row is still queued or in
  // flight AND we haven't already aborted. The button vanishes when
  // there's nothing left to skip.
  const hasPendingWork = $derived(
    items.some((i) => i.status === 'pending' || i.status === 'in-flight'),
  );
  const canCancel = $derived(
    dispatchState === 'submitting' && hasPendingWork && !(abortCtl?.signal.aborted ?? false),
  );

  function close(): void {
    onOpenChange(false);
  }
</script>

<Dialog {open} {onOpenChange}>
  <DialogContent side="bottom" class="max-w-2xl">
    <DialogHeader>
      <DialogTitle>
        Issue command on
        <span class="font-mono" data-testid="bulk-host-count">{hostIds.length}</span>
        {hostIds.length === 1 ? 'host' : 'hosts'}
      </DialogTitle>
      <DialogDescription>
        Step {step} of 4 ·
        {#if step === 1}Choose command type
        {:else if step === 2}Configure payload
        {:else if step === 3}Reason & approval
        {:else}Results
        {/if}
      </DialogDescription>
    </DialogHeader>

    <ol class="mb-3 flex items-center gap-1 text-xs text-muted" aria-label="Progress">
      {#each [1, 2, 3, 4] as n (n)}
        <li
          class={cn(
            'h-1 flex-1 rounded-full transition-colors',
            n <= step ? 'bg-accent' : 'bg-subtle',
          )}
          aria-current={n === step ? 'step' : undefined}
        ></li>
      {/each}
    </ol>

    <!-- Always-visible target host preview (except on results) -->
    {#if step < 4}
      <div
        class="mb-3 flex flex-wrap items-center gap-1 rounded-md border border-border-default bg-subtle px-2 py-2 text-xs"
        data-testid="bulk-target-hosts"
      >
        <span class="text-muted">Targets:</span>
        {#each hostnamesById.slice(0, 8) as name (name)}
          <Badge variant="secondary" class="font-mono">{name}</Badge>
        {/each}
        {#if hostnamesById.length > 8}
          <span class="text-muted">+{hostnamesById.length - 8} more</span>
        {/if}
      </div>
    {/if}

    <!-- ============ Step 1: type ============ -->
    {#if step === 1}
      <div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {#each COMMAND_TYPES as t (t.id)}
          <button
            type="button"
            class={cn(
              'flex flex-col items-start gap-1 rounded-lg border p-3 text-left transition-colors',
              chosenType === t.id
                ? 'border-accent bg-accent-bg'
                : 'border-border-default hover:bg-subtle',
            )}
            onclick={() => choose(t.id)}
            data-testid={`bulk-cmd-type-${t.id}`}
          >
            <div class="flex items-center gap-2">
              <Terminal class="size-4 text-muted" aria-hidden="true" />
              <span class="font-medium">{t.label}</span>
            </div>
            <span class="text-xs text-muted">{t.description}</span>
          </button>
        {/each}
      </div>
    {/if}

    <!-- ============ Step 2: payload ============ -->
    {#if step === 2 && chosenType}
      <div class="space-y-3 text-sm">
        {#if chosenType === 'shell'}
          <label class="block space-y-1">
            <span class="text-xs font-medium text-muted">Command</span>
            <Textarea
              bind:value={formState.shell.cmd}
              rows={4}
              placeholder="e.g. systemctl status nginx"
              aria-label="Shell command"
            />
          </label>
          <label class="block space-y-1">
            <span class="text-xs font-medium text-muted">Timeout (seconds)</span>
            <Input
              type="number"
              min="1"
              value={String(formState.shell.timeoutS)}
              oninput={(e) =>
                (formState.shell.timeoutS = Math.max(
                  1,
                  Number((e.target as HTMLInputElement).value) || 60,
                ))}
              aria-label="Timeout in seconds"
            />
          </label>
        {:else if chosenType === 'reboot'}
          <label class="block space-y-1">
            <span class="text-xs font-medium text-muted">
              Delay before reboot · {formState.reboot.delayS}s
            </span>
            <input
              type="range"
              min="0"
              max="300"
              step="5"
              value={formState.reboot.delayS}
              oninput={(e) =>
                (formState.reboot.delayS = Number((e.target as HTMLInputElement).value))}
              class="w-full accent-current"
              aria-label="Reboot delay seconds"
            />
          </label>
        {:else if chosenType === 'ssh-rotate'}
          <p class="text-sm text-muted">
            Each agent will generate a fresh Ed25519 signing key. The previous key is retired after
            the next successful command roundtrip.
          </p>
        {:else if chosenType === 'apt-update'}
          <label
            class="flex items-center justify-between gap-3 rounded-md border border-border-default p-3"
          >
            <div>
              <p class="text-sm font-medium">Reboot if needed</p>
              <p class="text-xs text-muted">
                After upgrade, schedule a reboot if any package requested it.
              </p>
            </div>
            <Switch bind:checked={formState['apt-update'].rebootIfNeeded} />
          </label>
        {:else if chosenType === 'exec-script'}
          <label class="block space-y-1">
            <span class="text-xs font-medium text-muted">Script name</span>
            <Input
              value={formState['exec-script'].script}
              oninput={(e) =>
                (formState['exec-script'].script = (e.target as HTMLInputElement).value)}
              placeholder="e.g. backup-postgres"
              aria-label="Script name"
            />
          </label>
          <label class="block space-y-1">
            <span class="text-xs font-medium text-muted">Args (space-separated)</span>
            <Input
              value={formState['exec-script'].args}
              oninput={(e) =>
                (formState['exec-script'].args = (e.target as HTMLInputElement).value)}
              placeholder="--full --gzip"
              aria-label="Script args"
            />
          </label>
        {/if}

        {#if previewPayload}
          <details class="rounded-md border border-border-default bg-subtle">
            <summary class="cursor-pointer px-3 py-2 text-xs text-muted">Payload preview</summary>
            <pre class="overflow-x-auto px-3 pb-3 font-mono text-xs">{previewPayload}</pre>
          </details>
        {/if}
      </div>
    {/if}

    <!-- ============ Step 3: reason + approval ============ -->
    {#if step === 3}
      <div class="space-y-3">
        <label class="block space-y-1">
          <span class="text-xs font-medium text-muted">Reason (optional)</span>
          <Textarea
            bind:value={reason}
            rows={3}
            placeholder="Why is this being issued on {hostIds.length} hosts? Helps approvers & audit."
            aria-label="Reason"
          />
        </label>
        <label
          class="flex items-center justify-between gap-3 rounded-md border border-border-default p-3"
        >
          <div>
            <p class="text-sm font-medium">Require human approval</p>
            <p class="text-xs text-muted">
              When on, each command waits in <span class="font-mono">pending-approval</span> until a second
              operator approves it. Approvals are still per-host.
            </p>
          </div>
          <Switch bind:checked={requiresApproval} />
        </label>
        {#if inlineError}
          <p class="rounded-md border border-danger bg-danger-bg p-2 text-xs text-danger-text">
            {inlineError}
          </p>
        {/if}
      </div>
    {/if}

    <!-- ============ Step 4: results ============ -->
    {#if step === 4}
      <div class="space-y-3">
        <div
          class="flex items-center justify-between text-xs text-muted"
          data-testid="bulk-progress"
        >
          <span>
            {progress.settled} of {progress.total} settled
          </span>
          <span>
            <span class="text-success-text">{okCount} OK</span>
            ·
            <span class="text-danger-text">{errorCount} failed</span>
            {#if cancelledCount > 0}
              ·
              <span class="text-muted" data-testid="bulk-cancelled-count">
                {cancelledCount} cancelled
              </span>
            {/if}
          </span>
        </div>
        <div class="max-h-72 overflow-y-auto rounded-md border border-border-default">
          <table class="w-full text-sm" data-testid="bulk-results-table">
            <thead class="bg-subtle text-xs uppercase tracking-wide text-muted">
              <tr>
                <th class="px-3 py-2 text-left">Host</th>
                <th class="px-3 py-2 text-left">Status</th>
                <th class="px-3 py-2 text-left">Details</th>
              </tr>
            </thead>
            <tbody>
              {#each items as item (item.host_id)}
                <tr
                  class="border-t border-border-subtle"
                  data-testid={`bulk-result-${item.hostname}`}
                  data-status={item.status}
                >
                  <td class="px-3 py-2 font-mono">{item.hostname}</td>
                  <td class="px-3 py-2">
                    {#if item.status === 'pending'}
                      <span class="text-xs text-muted">queued</span>
                    {:else if item.status === 'in-flight'}
                      <span class="inline-flex items-center gap-1 text-xs text-muted">
                        <Loader2 class="size-3 animate-spin" aria-hidden="true" />
                        sending
                      </span>
                    {:else if item.status === 'success'}
                      <span class="inline-flex items-center gap-1 text-xs text-success-text">
                        <Check class="size-3" aria-hidden="true" />
                        issued
                      </span>
                    {:else if item.status === 'cancelled'}
                      <span class="inline-flex items-center gap-1 text-xs text-muted">
                        <MinusCircle class="size-3" aria-hidden="true" />
                        cancelled
                      </span>
                    {:else}
                      <span class="inline-flex items-center gap-1 text-xs text-danger-text">
                        <AlertCircle class="size-3" aria-hidden="true" />
                        {item.httpStatus ?? 'error'}
                      </span>
                    {/if}
                  </td>
                  <td class="px-3 py-2 text-xs text-muted">
                    {#if item.status === 'error'}
                      {item.error ?? 'Unknown error'}
                    {:else if item.status === 'success' && item.command_id}
                      <span class="font-mono">{item.command_id.slice(0, 8)}</span>
                    {:else if item.status === 'cancelled'}
                      <span>Skipped — operator cancelled remaining</span>
                    {:else}
                      —
                    {/if}
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      </div>
    {/if}

    <DialogFooter>
      {#if step === 4}
        {#if dispatchState === 'submitting'}
          {#if canCancel}
            <Button variant="outline" onclick={cancelRemaining} data-testid="bulk-cancel-remaining">
              <Ban class="size-4" aria-hidden="true" />
              Cancel remaining
            </Button>
          {/if}
          <Button disabled>
            <Loader2 class="size-4 animate-spin" aria-hidden="true" />
            {#if abortCtl?.signal.aborted}
              Draining…
            {:else}
              Submitting…
            {/if}
          </Button>
        {:else}
          <Button onclick={close} data-testid="bulk-close">
            <X class="size-4" aria-hidden="true" />
            Close
          </Button>
        {/if}
      {:else}
        <Button variant="outline" onclick={goBack} disabled={step === 1}>
          <ArrowLeft class="size-4" aria-hidden="true" />
          Back
        </Button>
        {#if step < 3}
          <Button onclick={goNext} disabled={!canAdvance(step)} data-testid="bulk-next">
            Next
            <ArrowRight class="size-4" aria-hidden="true" />
          </Button>
        {:else}
          <Button onclick={submit} disabled={hostIds.length === 0} data-testid="bulk-submit">
            <Check class="size-4" aria-hidden="true" />
            Issue {hostIds.length === 1 ? 'command' : `${hostIds.length} commands`}
          </Button>
        {/if}
      {/if}
    </DialogFooter>
  </DialogContent>
</Dialog>
