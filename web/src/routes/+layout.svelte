<script lang="ts">
  import '../app.css';
  import type { Snippet } from 'svelte';
  import NavBar from '$lib/components/app/NavBar.svelte';
  import { Toaster } from '$lib/components/ui/sonner';

  type Props = {
    children: Snippet;
  };
  const { children }: Props = $props();
</script>

<div class="flex min-h-dvh flex-col bg-base text-default">
  <NavBar />
  <main id="main" class="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6">
    {@render children()}
  </main>
  <footer class="border-t border-border-subtle py-4 text-center text-xs text-muted">
    <span class="font-mono">remote-pulse</span> · ADR-0009 · /dash-next
  </footer>
</div>
<Toaster />
