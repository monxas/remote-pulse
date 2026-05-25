<script lang="ts">
  import { CheckCircle2, Clock, Server, ShieldAlert } from '@lucide/svelte';
  import { Card, CardContent, CardHeader, CardTitle } from '$lib/components/ui/card';
  import { Badge } from '$lib/components/ui/badge';
  import { userStore } from '$lib/stores/user.svelte';

  /**
   * Phase-0 landing page. Static stub numbers so the layout, tokens and
   * shadcn-svelte primitives can be visually verified end-to-end without
   * waiting on Phase 1's `/v1/dash/overview` endpoint. Real data lands in
   * ADR-0009 §7 Phase 1.
   */
  type Stat = {
    label: string;
    value: string;
    hint: string;
    Icon: typeof Server;
    tone: 'default' | 'success' | 'warn' | 'danger';
  };

  const stats: ReadonlyArray<Stat> = [
    { label: 'Total', value: '—', hint: 'fleet size', Icon: Server, tone: 'default' },
    { label: 'Online', value: '—', hint: 'last 60s', Icon: CheckCircle2, tone: 'success' },
    { label: 'Stale', value: '—', hint: '60-180s', Icon: Clock, tone: 'warn' },
    { label: 'Pending', value: '—', hint: 'approvals', Icon: ShieldAlert, tone: 'danger' },
  ];

  const toneToBadgeVariant = {
    default: 'secondary',
    success: 'success',
    warn: 'warn',
    danger: 'danger',
  } as const;
</script>

<section class="space-y-6">
  <header class="space-y-1">
    <h1 class="text-2xl font-bold tracking-tight">Hello fleet</h1>
    <p class="text-sm text-muted">
      Phase&nbsp;0 of ADR-0009. Wiring only — real data lands in Phase&nbsp;1.
    </p>
    {#if userStore.value}
      <p class="pt-2 text-sm">
        Signed in as <span class="font-mono">{userStore.value.user_email}</span>
        {#if userStore.value.user_role}
          <Badge variant="outline" class="ml-2 align-middle">
            {userStore.value.user_role}
          </Badge>
        {/if}
      </p>
    {/if}
  </header>

  <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
    {#each stats as stat (stat.label)}
      <Card>
        <CardHeader class="flex flex-row items-center justify-between gap-2 pb-2">
          <CardTitle class="text-sm font-medium text-muted">
            {stat.label}
          </CardTitle>
          <stat.Icon class="size-4 text-muted" aria-hidden="true" />
        </CardHeader>
        <CardContent>
          <div class="flex items-baseline gap-2">
            <span class="font-mono text-2xl font-semibold">{stat.value}</span>
            <Badge variant={toneToBadgeVariant[stat.tone]}>{stat.hint}</Badge>
          </div>
        </CardContent>
      </Card>
    {/each}
  </div>
</section>
