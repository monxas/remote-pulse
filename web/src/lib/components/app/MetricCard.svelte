<script lang="ts">
  import type { Component } from 'svelte';
  import { TrendingUp, TrendingDown, Minus } from '@lucide/svelte';
  import { Card, CardContent, CardHeader, CardTitle } from '$lib/components/ui/card';
  import { Badge } from '$lib/components/ui/badge';
  import { cn } from '$lib/utils';

  type Tone = 'default' | 'success' | 'warn' | 'danger';
  type Trend = { value: number; direction: 'up' | 'down' | 'neutral'; unit?: string };

  type Props = {
    label: string;
    value: string;
    hint?: string;
    tone?: Tone;
    Icon?: Component;
    trend?: Trend;
    loading?: boolean;
    class?: string;
  };
  const {
    label,
    value,
    hint,
    tone = 'default',
    Icon,
    trend,
    loading = false,
    class: className,
  }: Props = $props();

  const badgeVariant: Record<Tone, 'secondary' | 'success' | 'warn' | 'danger'> = {
    default: 'secondary',
    success: 'success',
    warn: 'warn',
    danger: 'danger',
  };

  const trendColor: Record<'up' | 'down' | 'neutral', string> = {
    up: 'text-success-text',
    down: 'text-danger-text',
    neutral: 'text-muted',
  };
</script>

<Card class={cn(className)}>
  <CardHeader class="flex flex-row items-center justify-between gap-2 pb-2">
    <CardTitle class="text-sm font-medium text-muted">{label}</CardTitle>
    {#if Icon}
      <Icon class="size-4 text-muted" aria-hidden="true" />
    {/if}
  </CardHeader>
  <CardContent>
    {#if loading}
      <div class="h-7 w-20 animate-pulse rounded bg-subtle" aria-hidden="true"></div>
      <div class="mt-2 h-4 w-16 animate-pulse rounded bg-subtle" aria-hidden="true"></div>
    {:else}
      <div class="flex items-baseline gap-2">
        <span class="font-mono text-2xl font-semibold tracking-tight">{value}</span>
        {#if hint}
          <Badge variant={badgeVariant[tone]}>{hint}</Badge>
        {/if}
      </div>
      {#if trend}
        <div
          class={cn(
            'mt-1 inline-flex items-center gap-1 font-mono text-xs',
            trendColor[trend.direction],
          )}
        >
          {#if trend.direction === 'up'}
            <TrendingUp class="size-3" aria-hidden="true" />
          {:else if trend.direction === 'down'}
            <TrendingDown class="size-3" aria-hidden="true" />
          {:else}
            <Minus class="size-3" aria-hidden="true" />
          {/if}
          <span>
            {trend.value > 0 ? '+' : ''}{trend.value.toFixed(1)}{trend.unit ?? ''}
          </span>
          <span class="text-muted">vs 24h ago</span>
        </div>
      {/if}
    {/if}
  </CardContent>
</Card>
