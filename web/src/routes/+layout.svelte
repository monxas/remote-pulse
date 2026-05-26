<script lang="ts">
  import '../app.css';
  import type { Snippet } from 'svelte';
  import { setContext } from 'svelte';
  import { QueryClientProvider } from '@tanstack/svelte-query';
  import NavBar from '$lib/components/app/NavBar.svelte';
  import CommandPalette from '$lib/components/app/CommandPalette.svelte';
  import LiveToasts from '$lib/components/app/LiveToasts.svelte';
  import { Toaster } from '$lib/components/ui/sonner';
  import { queryClient } from '$lib/queries/client';
  import { useLiveStream } from '$lib/queries/sse.svelte';

  type Props = {
    children: Snippet;
  };
  const { children }: Props = $props();

  // Boot the SSE stream once at layout mount. The hook registers its own
  // `onDestroy` so we don't need to clean up here. We stash the state in
  // a Svelte context so any descendant (e.g. the Fleet page header) can
  // pull the current connection status without re-creating the connection.
  const live = useLiveStream(queryClient);
  setContext('rp:live', live);
</script>

<QueryClientProvider client={queryClient}>
  <div class="flex min-h-dvh flex-col bg-base text-default pl-safe pr-safe">
    <NavBar />
    <main id="main" class="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6">
      {@render children()}
    </main>
    <footer class="border-t border-border-subtle py-4 pb-safe text-center text-xs text-muted">
      <span class="font-mono">remote-pulse</span> · ADR-0009 · /dash-next ·
      <kbd class="rounded border border-border-default bg-subtle px-1 font-mono">⌘K</kbd> palette
    </footer>
  </div>
  <CommandPalette />
  <LiveToasts />
</QueryClientProvider>
<Toaster />
