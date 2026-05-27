<script lang="ts">
  import { page } from '$app/stores';
  import { base, resolve } from '$app/paths';
  import {
    Activity,
    BarChart3,
    ListTree,
    Server,
    ShieldAlert,
    Terminal,
    KeyRound,
    Settings,
  } from '@lucide/svelte';
  import { cn } from '$lib/utils';
  import ThemeToggle from './ThemeToggle.svelte';
  import UserMenu from './UserMenu.svelte';
  import RecentActivityWidget from './RecentActivityWidget.svelte';

  const links = [
    { href: resolve('/'), label: 'Fleet', Icon: Activity, raw: '/' },
    { href: resolve('/hosts'), label: 'Hosts', Icon: Server, raw: '/hosts' },
    { href: resolve('/commands'), label: 'Commands', Icon: Terminal, raw: '/commands' },
    { href: resolve('/approvals'), label: 'Approvals', Icon: ShieldAlert, raw: '/approvals' },
    { href: resolve('/audit'), label: 'Audit', Icon: ListTree, raw: '/audit' },
    { href: resolve('/stats'), label: 'Stats', Icon: BarChart3, raw: '/stats' },
    { href: resolve('/enroll'), label: 'Enroll', Icon: KeyRound, raw: '/enroll' },
    { href: resolve('/settings'), label: 'Settings', Icon: Settings, raw: '/settings' },
  ] as const;

  function isActive(raw: string, pathname: string): boolean {
    if (raw === '/') return pathname === '/' || pathname === `${base}/` || pathname === base;
    const full = `${base}${raw}`;
    return pathname === full || pathname.startsWith(`${full}/`);
  }
</script>

<header class="sticky top-0 z-30 border-b border-border-subtle bg-base/80 backdrop-blur pt-safe">
  <div class="mx-auto flex h-14 w-full max-w-7xl items-center gap-4 px-4 sm:px-6">
    <a
      href={resolve('/')}
      class="touch-target inline-flex items-center gap-2 font-mono text-sm font-semibold tracking-tight"
    >
      <span class="inline-block size-2 rounded-full bg-success" aria-hidden="true"></span>
      remote-pulse
    </a>
    <nav class="ml-2 hidden flex-1 items-center gap-1 overflow-x-auto md:flex" aria-label="Primary">
      {#each links as link (link.href)}
        {@const active = isActive(link.raw, $page.url.pathname)}
        <a
          href={link.href}
          class={cn(
            'inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-sm transition-colors',
            active ? 'bg-subtle text-default' : 'text-muted hover:bg-subtle hover:text-default',
          )}
          aria-current={active ? 'page' : undefined}
          data-testid="nav-{link.label.toLowerCase()}"
        >
          <link.Icon class="size-4" aria-hidden="true" />
          {link.label}
        </a>
      {/each}
    </nav>
    <div class="ml-auto flex items-center gap-2">
      <RecentActivityWidget />
      <ThemeToggle />
      <UserMenu />
    </div>
  </div>
  <nav
    class="flex w-full items-center gap-1 overflow-x-auto px-4 pb-2 md:hidden"
    aria-label="Primary mobile"
  >
    {#each links as link (link.href)}
      {@const active = isActive(link.raw, $page.url.pathname)}
      <a
        href={link.href}
        class={cn(
          'inline-flex min-h-11 shrink-0 items-center gap-1.5 rounded-md px-3 py-2 text-sm transition-colors',
          active ? 'bg-subtle text-default' : 'text-muted hover:bg-subtle hover:text-default',
        )}
        aria-current={active ? 'page' : undefined}
      >
        <link.Icon class="size-4" aria-hidden="true" />
        {link.label}
      </a>
    {/each}
  </nav>
</header>
