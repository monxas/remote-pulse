<script lang="ts">
  import { ArrowLeft, Check, Loader2, RotateCw, ShieldAlert, X } from '@lucide/svelte';
  import { resolve } from '$app/paths';
  import { Button } from '#lib/components/ui/button/index.ts';
  import { Card, CardContent, CardHeader, CardTitle } from '#lib/components/ui/card/index.ts';
  import { Tabs, TabsList, TabsTrigger, TabsContent } from '#lib/components/ui/tabs/index.ts';
  import { Textarea } from '#lib/components/ui/textarea/index.ts';
  import {
    Dialog,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    DialogDescription,
  } from '#lib/components/ui/dialog/index.ts';
  import CommandStatusBadge from '#lib/components/app/CommandStatusBadge.svelte';
  import RelativeTime from '#lib/components/app/RelativeTime.svelte';
  import LiveBadge from '#lib/components/app/LiveBadge.svelte';
  import {
    createApproveMutation,
    createCommandDetailQuery,
    createRejectMutation,
    createRetryCommandMutation,
  } from '#lib/queries/index.ts';
  import { runeReadable } from '#lib/queries/reactive.svelte.ts';
  import { getLiveStream } from '#lib/queries/live-context.ts';
  import { IN_FLIGHT_STATUSES } from '#lib/api.ts';

  type Data = { commandId: string };
  const { data }: { data: Data } = $props();

  const live = getLiveStream();
  const cmdQuery = createCommandDetailQuery(runeReadable(() => data.commandId));
  const approve = createApproveMutation();
  const reject = createRejectMutation();
  const retry = createRetryCommandMutation();

  let outputTab = $state<'stdout' | 'stderr'>('stdout');
  let rejectOpen = $state(false);
  let rejectReason = $state('');
  let rejectError = $state<string | null>(null);

  async function doReject(id: string): Promise<void> {
    const r = rejectReason.trim();
    if (r.length < 3) {
      rejectError = 'Please give a reason (at least 3 characters).';
      return;
    }
    rejectError = null;
    try {
      await $reject.mutateAsync({ id, reason: r });
      rejectOpen = false;
      rejectReason = '';
    } catch {
      // toast handled
    }
  }

  const cmd = $derived($cmdQuery.data);
  const inFlight = $derived(cmd ? IN_FLIGHT_STATUSES.has(cmd.status) : false);
  const canRetry = $derived(
    !!cmd &&
      (cmd.status === 'failed' ||
        cmd.status === 'timeout' ||
        cmd.status === 'canceled' ||
        cmd.status === 'rejected'),
  );
  const isPending = $derived(cmd?.status === 'pending-approval');
</script>

<svelte:head>
  <title>{cmd?.command_type ?? 'Command'} · Remote-Pulse</title>
</svelte:head>

<section class="space-y-6">
  <div>
    <Button href={resolve('commands')} variant="ghost" size="sm" class="-ml-2">
      <ArrowLeft class="size-4" aria-hidden="true" />
      Commands
    </Button>
  </div>

  {#if $cmdQuery.isPending && !cmd}
    <div class="space-y-3" aria-busy="true">
      <div class="bg-subtle h-7 w-72 animate-pulse rounded"></div>
      <div class="bg-subtle h-4 w-96 animate-pulse rounded"></div>
    </div>
  {:else if $cmdQuery.isError}
    <Card>
      <CardHeader>
        <CardTitle>Could not load command</CardTitle>
      </CardHeader>
      <CardContent class="space-y-3">
        <p class="text-muted text-sm">{$cmdQuery.error?.message ?? 'Unknown error.'}</p>
        <Button onclick={() => void $cmdQuery.refetch()} size="sm">Reload</Button>
      </CardContent>
    </Card>
  {:else if cmd}
    <header class="space-y-3">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div class="flex flex-wrap items-center gap-3">
          <h1 class="font-mono text-xl font-semibold tracking-tight">
            {cmd.command_type}
          </h1>
          <CommandStatusBadge status={cmd.status} />
          <span class="text-muted text-xs">
            on
            <a
              class="text-accent-text font-mono hover:underline"
              href={resolve('/hosts/[id]', { id: cmd.host_id })}>{cmd.host_hostname}</a
            >
            ·
            <RelativeTime iso={cmd.issued_at} class="font-mono" />
          </span>
        </div>
        {#if live}
          <LiveBadge state={live.state} />
        {/if}
      </div>
      <p class="text-muted font-mono text-[11px] break-all">id {cmd.id}</p>
    </header>

    <!-- Actions -->
    <div class="flex flex-wrap items-center gap-2">
      {#if isPending}
        <Button onclick={() => $approve.mutate(cmd.id)} disabled={$approve.isPending}>
          {#if $approve.isPending}
            <Loader2 class="size-4 animate-spin" aria-hidden="true" />
          {:else}
            <Check class="size-4" aria-hidden="true" />
          {/if}
          Approve
        </Button>
        <Button variant="outline" onclick={() => (rejectOpen = true)}
          ><X class="size-4" aria-hidden="true" /> Reject</Button
        >
      {/if}
      {#if canRetry}
        <Button onclick={() => $retry.mutate(cmd.id)} disabled={$retry.isPending}>
          <RotateCw
            class={$retry.isPending ? 'size-4 animate-spin' : 'size-4'}
            aria-hidden="true"
          />
          Retry
        </Button>
      {/if}
      {#if cmd.status === 'rejected'}
        <Button variant="outline" onclick={() => $retry.mutate(cmd.id)} disabled={$retry.isPending}>
          <ShieldAlert class="size-4" aria-hidden="true" />
          Re-request approval
        </Button>
      {/if}
      {#if inFlight}
        <span class="text-muted text-xs">In-flight commands cannot be cancelled yet.</span>
      {/if}
    </div>

    <!-- Detail card -->
    <Card>
      <CardHeader>
        <CardTitle>Detail</CardTitle>
      </CardHeader>
      <CardContent class="space-y-4">
        <dl class="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-4">
          <div>
            <dt class="text-muted text-xs">Issued by</dt>
            <dd class="font-mono">{cmd.issued_by}</dd>
          </div>
          <div>
            <dt class="text-muted text-xs">Approved by</dt>
            <dd class="font-mono">{cmd.approved_by ?? '—'}</dd>
          </div>
          <div>
            <dt class="text-muted text-xs">Exit code</dt>
            <dd class="font-mono">{cmd.exit_code ?? '—'}</dd>
          </div>
          <div>
            <dt class="text-muted text-xs">Duration</dt>
            <dd class="font-mono">
              {cmd.duration_ms === null ? '—' : `${cmd.duration_ms}ms`}
            </dd>
          </div>
        </dl>

        <details open class="border-border-default rounded-md border">
          <summary class="text-muted cursor-pointer px-3 py-2 text-xs font-medium">
            Payload
          </summary>
          <pre
            class="bg-subtle max-h-72 overflow-auto rounded-b-md p-3 font-mono text-xs whitespace-pre-wrap">{JSON.stringify(
              cmd.command_payload,
              null,
              2,
            )}</pre>
        </details>

        {#if cmd.rejected_reason}
          <div class="border-danger bg-danger-bg text-danger-text rounded-md border p-2 text-xs">
            <span class="font-medium">Rejected:</span>
            {cmd.rejected_reason}
          </div>
        {/if}

        <!-- Timeline -->
        <div>
          <h3 class="text-muted mb-2 text-xs font-medium">Timeline</h3>
          <ol class="space-y-1 text-xs">
            <li class="flex items-center gap-2">
              <span class="bg-accent inline-block size-2 rounded-full" aria-hidden="true"></span>
              issued <RelativeTime iso={cmd.issued_at} class="text-muted font-mono" />
            </li>
            {#if cmd.approved_by}
              <li class="flex items-center gap-2">
                <span class="bg-success inline-block size-2 rounded-full" aria-hidden="true"></span>
                approved by <span class="font-mono">{cmd.approved_by}</span>
              </li>
            {/if}
            {#if cmd.completed_at}
              <li class="flex items-center gap-2">
                <span
                  class={`inline-block size-2 rounded-full ${cmd.status === 'succeeded' ? 'bg-success' : 'bg-danger'}`}
                  aria-hidden="true"
                ></span>
                {cmd.status}
                <RelativeTime iso={cmd.completed_at} class="text-muted font-mono" />
              </li>
            {/if}
          </ol>
        </div>
      </CardContent>
    </Card>

    <!-- Output -->
    <Card>
      <CardHeader>
        <CardTitle>Output</CardTitle>
      </CardHeader>
      <CardContent>
        <!-- Mobile: tabs -->
        <div class="sm:hidden">
          <Tabs bind:value={outputTab}>
            <TabsList>
              <TabsTrigger value="stdout">stdout</TabsTrigger>
              <TabsTrigger value="stderr">stderr</TabsTrigger>
            </TabsList>
            <TabsContent value="stdout">
              <pre
                class="border-border-default bg-subtle mt-2 max-h-96 overflow-auto rounded-md border p-2 font-mono text-xs break-words whitespace-pre-wrap">{cmd.stdout ??
                  '(empty)'}</pre>
            </TabsContent>
            <TabsContent value="stderr">
              <pre
                class="border-border-default bg-subtle text-danger-text mt-2 max-h-96 overflow-auto rounded-md border p-2 font-mono text-xs break-words whitespace-pre-wrap">{cmd.stderr ??
                  '(empty)'}</pre>
            </TabsContent>
          </Tabs>
        </div>
        <!-- Desktop: side-by-side -->
        <div class="hidden grid-cols-2 gap-3 sm:grid">
          <div>
            <h4 class="text-muted mb-1 text-xs font-medium">stdout</h4>
            <pre
              class="border-border-default bg-subtle max-h-96 overflow-auto rounded-md border p-2 font-mono text-xs break-words whitespace-pre-wrap">{cmd.stdout ??
                '(empty)'}</pre>
          </div>
          <div>
            <h4 class="text-danger-text mb-1 text-xs font-medium">stderr</h4>
            <pre
              class="border-border-default bg-subtle text-danger-text max-h-96 overflow-auto rounded-md border p-2 font-mono text-xs break-words whitespace-pre-wrap">{cmd.stderr ??
                '(empty)'}</pre>
          </div>
        </div>
      </CardContent>
    </Card>

    <Dialog bind:open={rejectOpen} onOpenChange={(v) => (rejectOpen = v)}>
      <DialogContent side="bottom">
        <DialogHeader>
          <DialogTitle>Reject command</DialogTitle>
          <DialogDescription>Reason will be surfaced in the audit log.</DialogDescription>
        </DialogHeader>
        <Textarea
          bind:value={rejectReason}
          rows={4}
          placeholder="e.g. wrong host group — please retarget"
          aria-label="Rejection reason"
        />
        {#if rejectError}
          <p class="text-danger-text mt-2 text-xs">{rejectError}</p>
        {/if}
        <DialogFooter>
          <Button
            variant="outline"
            onclick={() => (rejectOpen = false)}
            disabled={$reject.isPending}>Cancel</Button
          >

          <Button variant="danger" onclick={() => doReject(cmd.id)} disabled={$reject.isPending}>
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
  {/if}
</section>
