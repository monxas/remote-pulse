<script lang="ts">
  import { Search } from '@lucide/svelte';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { resolve } from '$app/paths';
  import { SvelteURLSearchParams } from 'svelte/reactivity';
  import { Input } from '$lib/components/ui/input';
  import { cn } from '$lib/utils';
  import WindowSelector from './WindowSelector.svelte';
  import type { HostStatus } from '$lib/api';

  type Props = {
    groups: ReadonlyArray<string>;
  };
  const { groups }: Props = $props();

  // Read current state from URL search params (single source of truth so
  // refreshes don't clobber the operator's filter selection).
  const params = $derived($page.url.searchParams);
  const q = $derived(params.get('q') ?? '');
  const group = $derived(params.get('group') ?? '');
  const status = $derived((params.get('status') ?? '') as HostStatus | '');
  const window = $derived(params.get('window') ?? '5m');

  // Mirror the URL `q` param into a local state we can mutate from the
  // input. We can't use a writable $derived here because we also flush
  // user-typed values into the URL on a 250 ms debounce — the two
  // directions of the binding are independent.
  // eslint-disable-next-line svelte/prefer-writable-derived
  let qLocal = $state('');
  $effect(() => {
    qLocal = q;
  });

  let debounceTimer: ReturnType<typeof setTimeout> | null = null;

  function updateUrl(patch: Record<string, string | null>): void {
    const next = new SvelteURLSearchParams($page.url.searchParams);
    for (const [k, v] of Object.entries(patch)) {
      if (v === null || v === '') next.delete(k);
      else next.set(k, v);
    }
    const qs = next.toString();
    const target = `${resolve('/')}${qs ? `?${qs}` : ''}` as `/${string}`;
    // The `resolve` call above already validated the route; the rule can't
    // see through the template concatenation we use to append `?qs`.
    // eslint-disable-next-line svelte/no-navigation-without-resolve
    void goto(target, {
      keepFocus: true,
      noScroll: true,
      replaceState: true,
    });
  }

  function onSearchInput(ev: Event): void {
    qLocal = (ev.target as HTMLInputElement).value;
    if (debounceTimer !== null) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => updateUrl({ q: qLocal || null }), 250);
  }

  function clearAll(): void {
    qLocal = '';
    updateUrl({ q: null, group: null, status: null, window: null });
  }

  const statuses: ReadonlyArray<{ value: HostStatus | ''; label: string }> = [
    { value: '', label: 'Any status' },
    { value: 'online', label: 'Online' },
    { value: 'stale', label: 'Stale' },
    { value: 'offline', label: 'Offline' },
    { value: 'unknown', label: 'Unknown' },
  ];
</script>

<div
  class="flex flex-col gap-3 rounded-lg border border-border-default bg-elevated p-3 sm:flex-row sm:items-center"
>
  <div class="relative flex-1">
    <Search
      class="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted"
      aria-hidden="true"
    />
    <Input
      value={qLocal}
      oninput={onSearchInput}
      placeholder="Search hostnames…"
      class="pl-8"
      aria-label="Search hosts"
    />
  </div>

  <div class="flex items-center gap-2">
    <label class="flex items-center gap-2 text-xs text-muted">
      <span class="sr-only sm:not-sr-only">Group</span>
      <select
        value={group}
        onchange={(e) => updateUrl({ group: (e.target as HTMLSelectElement).value || null })}
        class={cn(
          'h-9 rounded-md border border-border-default bg-base px-2 text-sm text-default',
          'focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
        )}
      >
        <option value="">All groups</option>
        {#each groups as g (g)}
          <option value={g}>{g}</option>
        {/each}
      </select>
    </label>

    <label class="flex items-center gap-2 text-xs text-muted">
      <span class="sr-only sm:not-sr-only">Status</span>
      <select
        value={status}
        onchange={(e) => updateUrl({ status: (e.target as HTMLSelectElement).value || null })}
        class={cn(
          'h-9 rounded-md border border-border-default bg-base px-2 text-sm text-default',
          'focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
        )}
      >
        {#each statuses as s (s.value)}
          <option value={s.value}>{s.label}</option>
        {/each}
      </select>
    </label>
  </div>

  <WindowSelector
    value={window}
    onchange={(next) => updateUrl({ window: next === '5m' ? null : next })}
    label="Sparkline window"
  />

  {#if q || group || status || (window && window !== '5m')}
    <button
      type="button"
      class="text-xs text-accent-text underline-offset-4 hover:underline"
      onclick={clearAll}
    >
      Clear filters
    </button>
  {/if}
</div>
