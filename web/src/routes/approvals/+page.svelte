<script lang="ts">
  import { CheckCircle2 } from '@lucide/svelte';
  import { Badge } from '$lib/components/ui/badge';
  import { Card, CardContent } from '$lib/components/ui/card';
  import { Button } from '$lib/components/ui/button';
  import ApprovalCard from '$lib/components/app/ApprovalCard.svelte';
  import LiveBadge from '$lib/components/app/LiveBadge.svelte';
  import PullToRefresh from '$lib/components/app/PullToRefresh.svelte';
  import { createPendingApprovalsQuery } from '$lib/queries';
  import { getLiveStream } from '$lib/queries/live-context';

  const live = getLiveStream();
  const approvals = createPendingApprovalsQuery();

  const list = $derived($approvals.data?.approvals ?? []);
</script>

<svelte:head>
  <title>Approvals · Remote-Pulse</title>
</svelte:head>

<PullToRefresh onRefresh={() => $approvals.refetch()}>
<section class="space-y-6">
  <header class="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
    <div>
      <h1 class="text-2xl font-bold tracking-tight">
        Approvals
        {#if list.length > 0}
          <Badge variant="warn" class="ml-2 align-middle">{list.length} pending</Badge>
        {/if}
      </h1>
      <p class="text-sm text-muted">Commands waiting on a second operator before they execute.</p>
    </div>
    {#if live}
      <LiveBadge state={live.state} />
    {/if}
  </header>

  {#if $approvals.isPending && !$approvals.data}
    <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-busy="true">
      {#each [0, 1, 2] as i (i)}
        <div class="h-48 animate-pulse rounded-lg border border-border-subtle bg-subtle"></div>
      {/each}
    </div>
  {:else if $approvals.isError}
    <Card>
      <CardContent class="space-y-3 py-6">
        <p class="text-sm text-muted">
          Could not load approvals: {$approvals.error?.message ?? 'unknown error'}.
        </p>
        <Button size="sm" onclick={() => void $approvals.refetch()}>Reload</Button>
      </CardContent>
    </Card>
  {:else if list.length === 0}
    <Card>
      <CardContent class="flex flex-col items-center gap-3 py-12 text-center">
        <CheckCircle2 class="size-8 text-success" aria-hidden="true" />
        <p class="text-sm text-muted">Nothing to approve. You are caught up.</p>
      </CardContent>
    </Card>
  {:else}
    <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {#each list as cmd (cmd.id)}
        <ApprovalCard command={cmd} />
      {/each}
    </div>
  {/if}
</section>
</PullToRefresh>
