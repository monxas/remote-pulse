<script lang="ts">
  import { ArrowLeft, ArrowRight, Check, Loader2, Search, Terminal } from '@lucide/svelte';
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
  import { createHostsQuery, createIssueCommandMutation } from '$lib/queries';
  import { runeReadable } from '$lib/queries/reactive.svelte';
  import {
    COMMAND_TYPES,
    DEFAULT_FORM_STATE,
    buildPayload,
    isHostSelectionValid,
    isPayloadValid,
    summarizePayload,
    type CommandFormState,
    type CommandTypeId,
  } from '$lib/commands/types';

  type Props = {
    open: boolean;
    onOpenChange: (next: boolean) => void;
    /** Optional pre-selected host (e.g. from a host-detail page). */
    initialHostId?: string;
  };

  let { open = $bindable(false), onOpenChange, initialHostId }: Props = $props();

  type Step = 1 | 2 | 3 | 4 | 5;
  let step = $state<Step>(1);

  let hostSearch = $state('');
  let selectedHostIds = $state<string[]>([]);
  let chosenType = $state<CommandTypeId | null>(null);
  let formState = $state<CommandFormState>(structuredClone(DEFAULT_FORM_STATE));
  let reason = $state('');
  let requiresApproval = $state(true);
  let inlineError = $state<string | null>(null);

  const hostsQuery = createHostsQuery(runeReadable(() => ({})));
  const issueMutation = createIssueCommandMutation();

  const allHosts = $derived($hostsQuery.data?.hosts ?? []);

  const filteredHosts = $derived.by(() => {
    const q = hostSearch.trim().toLowerCase();
    if (q.length === 0) return allHosts;
    return allHosts.filter(
      (h) => h.hostname.toLowerCase().includes(q) || h.group_name.toLowerCase().includes(q),
    );
  });

  const groupedHosts = $derived.by(() => {
    // Group filtered hosts by `group_name` into a sorted array of tuples.
    // We avoid `Map` here because eslint-plugin-svelte (correctly) rejects
    // plain Map inside reactive scopes — but in our case the grouping is
    // pure (rebuilt from a $derived input) so a record + index lookup is
    // both simpler and lint-clean.
    const byGroup: Record<string, typeof filteredHosts> = Object.create(null);
    for (const h of filteredHosts) {
      const list = byGroup[h.group_name];
      if (list) list.push(h);
      else byGroup[h.group_name] = [h];
    }
    return Object.entries(byGroup).sort(([a], [b]) => a.localeCompare(b));
  });

  function resetState(): void {
    step = 1;
    hostSearch = '';
    selectedHostIds = initialHostId ? [initialHostId] : [];
    chosenType = null;
    formState = structuredClone(DEFAULT_FORM_STATE);
    reason = '';
    requiresApproval = true;
    inlineError = null;
  }

  // Reset whenever the dialog reopens so each open is a clean session.
  $effect(() => {
    if (open) resetState();
  });

  function toggleHost(id: string): void {
    selectedHostIds = selectedHostIds.includes(id)
      ? selectedHostIds.filter((x) => x !== id)
      : [...selectedHostIds, id];
  }

  function toggleAllVisible(): void {
    const visibleIds = filteredHosts.map((h) => h.id);
    const allSelected = visibleIds.every((id) => selectedHostIds.includes(id));
    if (allSelected) {
      selectedHostIds = selectedHostIds.filter((id) => !visibleIds.includes(id));
    } else {
      const set = new Set([...selectedHostIds, ...visibleIds]);
      selectedHostIds = Array.from(set);
    }
  }

  function choose(type: CommandTypeId): void {
    chosenType = type;
    requiresApproval = COMMAND_TYPES.find((t) => t.id === type)?.defaultRequiresApproval ?? true;
    step = 3;
  }

  function canAdvance(current: Step): boolean {
    switch (current) {
      case 1:
        return isHostSelectionValid(selectedHostIds);
      case 2:
        return chosenType !== null;
      case 3:
        return chosenType !== null && isPayloadValid(chosenType, formState);
      case 4:
        return true;
      case 5:
        return true;
    }
  }

  function goNext(): void {
    if (!canAdvance(step)) return;
    if (step < 5) step = (step + 1) as Step;
  }

  function goBack(): void {
    if (step > 1) step = (step - 1) as Step;
  }

  async function submit(): Promise<void> {
    if (!chosenType) return;
    inlineError = null;
    let payload: Record<string, unknown>;
    try {
      payload = buildPayload(chosenType, formState);
    } catch (err) {
      inlineError = err instanceof Error ? err.message : 'Invalid payload.';
      return;
    }
    try {
      await $issueMutation.mutateAsync({
        host_ids: selectedHostIds,
        command_type: chosenType,
        command_payload: payload,
        reason: reason.trim() || undefined,
        requires_approval: requiresApproval,
      });
      onOpenChange(false);
    } catch {
      // Toast handled by mutation onError; keep dialog open so user can retry.
    }
  }

  const previewPayload = $derived.by(() => {
    if (!chosenType) return '';
    try {
      return summarizePayload(buildPayload(chosenType, formState));
    } catch {
      return '';
    }
  });
</script>

<Dialog bind:open {onOpenChange}>
  <DialogContent side="bottom" class="max-w-2xl">
    <DialogHeader>
      <DialogTitle>Issue command</DialogTitle>
      <DialogDescription>
        Step {step} of 5 ·
        {#if step === 1}Pick hosts
        {:else if step === 2}Choose command type
        {:else if step === 3}Configure payload
        {:else if step === 4}Reason & approval
        {:else}Review & confirm
        {/if}
      </DialogDescription>
    </DialogHeader>

    <ol class="mb-3 flex items-center gap-1 text-xs text-muted" aria-label="Progress">
      {#each [1, 2, 3, 4, 5] as n (n)}
        <li
          class={cn(
            'h-1 flex-1 rounded-full transition-colors',
            n <= step ? 'bg-accent' : 'bg-subtle',
          )}
          aria-current={n === step ? 'step' : undefined}
        ></li>
      {/each}
    </ol>

    <!-- ============ Step 1: hosts ============ -->
    {#if step === 1}
      <div class="space-y-3">
        <div class="relative">
          <Search
            class="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted"
            aria-hidden="true"
          />
          <Input
            value={hostSearch}
            oninput={(e) => (hostSearch = (e.target as HTMLInputElement).value)}
            placeholder="Search hosts or groups…"
            class="pl-8"
            aria-label="Search hosts"
          />
        </div>
        <div class="flex items-center justify-between text-xs text-muted">
          <span>
            {selectedHostIds.length} selected · {filteredHosts.length} visible
          </span>
          <button
            type="button"
            class="text-accent-text underline-offset-4 hover:underline"
            onclick={toggleAllVisible}
          >
            Toggle visible
          </button>
        </div>
        <div class="max-h-72 space-y-3 overflow-y-auto rounded-md border border-border-default p-2">
          {#if $hostsQuery.isPending}
            <p class="py-4 text-center text-xs text-muted">Loading hosts…</p>
          {:else if groupedHosts.length === 0}
            <p class="py-4 text-center text-xs text-muted">No matching hosts.</p>
          {:else}
            {#each groupedHosts as [groupName, groupHosts] (groupName)}
              <div>
                <h4 class="px-1 pb-1 text-[10px] font-medium uppercase tracking-wide text-muted">
                  {groupName}
                </h4>
                <ul class="space-y-0.5">
                  {#each groupHosts as host (host.id)}
                    {@const checked = selectedHostIds.includes(host.id)}
                    <li>
                      <label
                        class={cn(
                          'flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors',
                          checked ? 'bg-accent-bg text-accent-text' : 'hover:bg-subtle',
                        )}
                      >
                        <input
                          type="checkbox"
                          {checked}
                          onchange={() => toggleHost(host.id)}
                          class="size-3.5 accent-current"
                          aria-label={`Select ${host.hostname}`}
                        />
                        <span class="font-mono">{host.hostname}</span>
                        <span class="ml-auto text-xs text-muted">{host.status}</span>
                      </label>
                    </li>
                  {/each}
                </ul>
              </div>
            {/each}
          {/if}
        </div>
      </div>
    {/if}

    <!-- ============ Step 2: type ============ -->
    {#if step === 2}
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

    <!-- ============ Step 3: payload ============ -->
    {#if step === 3 && chosenType}
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
            The agent will generate a fresh Ed25519 signing key. The previous key is retired after
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

    <!-- ============ Step 4: reason + approval ============ -->
    {#if step === 4}
      <div class="space-y-3">
        <label class="block space-y-1">
          <span class="text-xs font-medium text-muted">Reason (optional)</span>
          <Textarea
            bind:value={reason}
            rows={3}
            placeholder="Why is this being issued? Helps approvers & audit."
            aria-label="Reason"
          />
        </label>
        <label
          class="flex items-center justify-between gap-3 rounded-md border border-border-default p-3"
        >
          <div>
            <p class="text-sm font-medium">Require human approval</p>
            <p class="text-xs text-muted">
              When on, the command waits in <span class="font-mono">pending-approval</span> until a second
              operator approves it.
            </p>
          </div>
          <Switch bind:checked={requiresApproval} />
        </label>
      </div>
    {/if}

    <!-- ============ Step 5: confirm ============ -->
    {#if step === 5 && chosenType}
      <div class="space-y-3 text-sm">
        <dl class="grid grid-cols-3 gap-2">
          <dt class="text-muted">Hosts</dt>
          <dd class="col-span-2">
            <div class="flex flex-wrap gap-1">
              {#each selectedHostIds as id (id)}
                {@const h = allHosts.find((x) => x.id === id)}
                <Badge variant="secondary" class="font-mono">{h?.hostname ?? id}</Badge>
              {/each}
            </div>
          </dd>
          <dt class="text-muted">Type</dt>
          <dd class="col-span-2 font-mono">{chosenType}</dd>
          <dt class="text-muted">Approval</dt>
          <dd class="col-span-2">{requiresApproval ? 'required' : 'auto'}</dd>
          {#if reason.trim()}
            <dt class="text-muted">Reason</dt>
            <dd class="col-span-2">{reason.trim()}</dd>
          {/if}
          <dt class="text-muted">Payload</dt>
          <dd class="col-span-2">
            <pre
              class="overflow-x-auto rounded-md border border-border-default bg-subtle p-2 font-mono text-xs">{previewPayload}</pre>
          </dd>
        </dl>
        {#if inlineError}
          <p class="rounded-md border border-danger bg-danger-bg p-2 text-xs text-danger-text">
            {inlineError}
          </p>
        {/if}
      </div>
    {/if}

    <DialogFooter>
      <Button variant="outline" onclick={goBack} disabled={step === 1 || $issueMutation.isPending}>
        <ArrowLeft class="size-4" aria-hidden="true" />
        Back
      </Button>
      {#if step < 5}
        <Button onclick={goNext} disabled={!canAdvance(step)}>
          Next
          <ArrowRight class="size-4" aria-hidden="true" />
        </Button>
      {:else}
        <Button onclick={submit} disabled={$issueMutation.isPending}>
          {#if $issueMutation.isPending}
            <Loader2 class="size-4 animate-spin" aria-hidden="true" />
            Issuing…
          {:else}
            <Check class="size-4" aria-hidden="true" />
            Issue {selectedHostIds.length === 1 ? 'command' : `${selectedHostIds.length} commands`}
          {/if}
        </Button>
      {/if}
    </DialogFooter>
  </DialogContent>
</Dialog>
