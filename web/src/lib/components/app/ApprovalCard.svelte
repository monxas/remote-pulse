<script lang="ts">
  import { Check, Loader2, X } from '@lucide/svelte';
  import { resolve } from '$app/paths';
  import type { CommandRecord } from '$lib/api';
  import { Card, CardContent, CardHeader, CardTitle } from '$lib/components/ui/card';
  import { Button } from '$lib/components/ui/button';
  import { Badge } from '$lib/components/ui/badge';
  import { Textarea } from '$lib/components/ui/textarea';
  import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogDescription,
    DialogFooter,
  } from '$lib/components/ui/dialog';
  import { createApproveMutation, createRejectMutation } from '$lib/queries';
  import RelativeTime from './RelativeTime.svelte';

  type Props = { command: CommandRecord };
  const { command }: Props = $props();

  const approve = createApproveMutation();
  const reject = createRejectMutation();

  let rejectOpen = $state(false);
  let rejectReason = $state('');
  let rejectError = $state<string | null>(null);

  const detailHref = $derived(resolve('/commands/[id]', { id: command.id }));

  async function doReject(): Promise<void> {
    const reason = rejectReason.trim();
    if (reason.length < 3) {
      rejectError = 'Please give a reason (at least 3 characters).';
      return;
    }
    rejectError = null;
    try {
      await $reject.mutateAsync({ id: command.id, reason });
      rejectOpen = false;
      rejectReason = '';
    } catch {
      // toast handled by mutation
    }
  }

  function summarisePayload(payload: Record<string, unknown>): string {
    if ('cmd' in payload && typeof payload.cmd === 'string') return payload.cmd;
    if ('script' in payload && typeof payload.script === 'string') {
      const args = Array.isArray(payload.args) ? ` ${payload.args.join(' ')}` : '';
      return `${payload.script}${args}`;
    }
    return JSON.stringify(payload);
  }
</script>

<Card class="flex flex-col">
  <CardHeader>
    <div class="flex items-start justify-between gap-2">
      <div>
        <CardTitle class="font-mono text-base">{command.command_type}</CardTitle>
        <p class="mt-1 text-xs text-muted">
          on <a
            class="font-mono text-accent-text hover:underline"
            href={resolve('/hosts/[id]', { id: command.host_id })}>{command.host_hostname}</a
          >
          ·
          <RelativeTime iso={command.issued_at} />
        </p>
      </div>
      <Badge variant="warn">Pending</Badge>
    </div>
  </CardHeader>
  <CardContent class="flex flex-1 flex-col gap-3">
    <pre
      class="max-h-32 overflow-auto whitespace-pre-wrap rounded-md border border-border-default bg-subtle p-2 font-mono text-xs">{summarisePayload(
        command.command_payload,
      )}</pre>
    <dl class="grid grid-cols-2 gap-2 text-xs">
      <div>
        <dt class="text-muted">Issued by</dt>
        <dd class="font-mono">{command.issued_by}</dd>
      </div>
      {#if command.command_payload && Object.keys(command.command_payload).length > 0}
        <div>
          <dt class="text-muted">Args</dt>
          <dd class="font-mono">{Object.keys(command.command_payload).length} field(s)</dd>
        </div>
      {/if}
    </dl>
    <div class="mt-auto flex flex-wrap items-center justify-end gap-2 pt-3">
      <Button href={detailHref} variant="ghost" size="sm">Details</Button>
      <Button
        variant="outline"
        size="sm"
        onclick={() => (rejectOpen = true)}
        disabled={$approve.isPending || $reject.isPending}
      >
        <X class="size-4" aria-hidden="true" />
        Reject
      </Button>
      <Button
        size="sm"
        onclick={() => $approve.mutate(command.id)}
        disabled={$approve.isPending || $reject.isPending}
      >
        {#if $approve.isPending}
          <Loader2 class="size-4 animate-spin" aria-hidden="true" />
        {:else}
          <Check class="size-4" aria-hidden="true" />
        {/if}
        Approve
      </Button>
    </div>
  </CardContent>
</Card>

<Dialog bind:open={rejectOpen} onOpenChange={(v) => (rejectOpen = v)}>
  <DialogContent side="bottom">
    <DialogHeader>
      <DialogTitle>Reject command</DialogTitle>
      <DialogDescription>
        Tell the requester why. They will see this reason in the audit log and command detail.
      </DialogDescription>
    </DialogHeader>
    <Textarea
      bind:value={rejectReason}
      rows={4}
      placeholder="e.g. wrong host group — please retarget"
      aria-label="Rejection reason"
    />
    {#if rejectError}
      <p class="mt-2 text-xs text-danger-text">{rejectError}</p>
    {/if}
    <DialogFooter>
      <Button variant="outline" onclick={() => (rejectOpen = false)} disabled={$reject.isPending}>
        Cancel
      </Button>
      <Button variant="danger" onclick={doReject} disabled={$reject.isPending}>
        {#if $reject.isPending}
          <Loader2 class="size-4 animate-spin" aria-hidden="true" />
          Rejecting…
        {:else}
          Reject
        {/if}
      </Button>
    </DialogFooter>
  </DialogContent>
</Dialog>
