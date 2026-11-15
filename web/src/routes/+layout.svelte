<script lang="ts">
  import '../app.css';
  import type { Snippet } from 'svelte';
  import { setContext } from 'svelte';
  import { QueryClientProvider } from '@tanstack/svelte-query';
  import NavBar from '#lib/components/app/NavBar.svelte';
  import CommandPalette from '#lib/components/app/CommandPalette.svelte';
  import LiveToasts from '#lib/components/app/LiveToasts.svelte';
  import LiveNotifications from '#lib/components/app/LiveNotifications.svelte';
  import { Toaster } from '#lib/components/ui/sonner/index.ts';
  import { queryClient } from '#lib/queries/client.ts';
  import { useLiveStream } from '#lib/queries/sse.svelte.ts';

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
  <div class="bg-base text-default pl-safe pr-safe flex min-h-dvh flex-col">
    <NavBar />
    <main id="main" class="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6">
      {@render children()}
    </main>
    <footer class="border-border-subtle pb-safe text-muted border-t py-4 text-center text-xs">
      <span class="font-mono">remote-pulse</span> · ADR-0009 · /dash-next ·
      <kbd class="border-border-default bg-subtle rounded border px-1 font-mono">⌘K</kbd> palette
    </footer>
  </div>
  <CommandPalette />
  <LiveToasts />
  <LiveNotifications />
</QueryClientProvider>
<Toaster />
