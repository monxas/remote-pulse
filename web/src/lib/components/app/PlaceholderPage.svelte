<script lang="ts">
  import { ArrowLeft } from '@lucide/svelte';
  import { resolve } from '$app/paths';
  import { Card, CardContent, CardHeader, CardTitle } from '#lib/components/ui/card/index.ts';
  import { Button } from '#lib/components/ui/button/index.ts';

  type Props = {
    title: string;
    phase: string;
    description?: string;
  };
  const { title, phase, description }: Props = $props();
</script>

<svelte:head>
  <title>{title} · Remote-Pulse</title>
</svelte:head>

<section class="space-y-6">
  <header class="space-y-1">
    <h1 class="text-2xl font-bold tracking-tight">{title}</h1>
    <p class="text-muted text-sm">Coming in {phase}.</p>
  </header>
  <Card>
    <CardHeader>
      <CardTitle>Not yet available</CardTitle>
    </CardHeader>
    <CardContent class="space-y-4">
      <p class="text-muted text-sm">
        {description ?? `This screen is scoped for ${phase} of ADR-0009. Check back soon.`}
      </p>

      <Button href={resolve('/')} variant="outline" size="sm">
        <ArrowLeft class="size-4" aria-hidden="true" />
        Back to fleet
      </Button>
    </CardContent>
  </Card>
</section>
