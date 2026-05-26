<script lang="ts">
  /**
   * Bell-icon dropdown in the topbar that surfaces the last ~10 SSE
   * events as a "recent activity" feed.
   *
   * - The badge shows the count of events with `ts > lastSeenTs`, where
   *   `lastSeenTs` is persisted in localStorage so unread state survives
   *   reloads.
   * - Opening the popover marks everything as read.
   * - Clicking an item navigates to the relevant resource (host, command,
   *   approvals queue, audit row) and closes the popover.
   * - When the live stream is in "failed" state we still render the
   *   widget (operators want to see recent history even after the
   *   connection died) but show a small notice in the empty state.
   */
  import { onMount } from 'svelte';
  import { Bell } from '@lucide/svelte';
  import { goto } from '$app/navigation';
  import { resolve } from '$app/paths';
  import RelativeTime from './RelativeTime.svelte';
  import { getLiveStream } from '$lib/queries/live-context';
  import { cn } from '$lib/utils';
  import type { SseEvent } from '$lib/queries/sse.svelte';

  const STORAGE_KEY = 'rp:lastSeenActivityTs';
  const VISIBLE_LIMIT = 10;

  const live = getLiveStream();

  let open = $state(false);
  let lastSeenTs = $state(0);
  let rootEl = $state<HTMLDivElement | null>(null);

  onMount(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) lastSeenTs = parseInt(raw, 10) || 0;
    } catch {
      // localStorage disabled (Safari private, etc.) — fall back to 0.
    }
  });

  function persistLastSeen(ts: number): void {
    lastSeenTs = ts;
    try {
      window.localStorage.setItem(STORAGE_KEY, String(ts));
    } catch {
      // ignore
    }
  }

  function describe(e: SseEvent): { title: string; subtitle: string; href: string | null } {
    const data = e.data && typeof e.data === 'object' ? (e.data as Record<string, unknown>) : null;
    const hostId = typeof data?.host_id === 'string' ? data.host_id : null;
    const commandId = typeof data?.command_id === 'string' ? data.command_id : null;
    const groupName = typeof data?.group_name === 'string' ? data.group_name : null;
    const status = typeof data?.status === 'string' ? data.status : null;
    const issuedBy = typeof data?.issued_by === 'string' ? data.issued_by : null;
    const resolvedBy = typeof data?.resolved_by === 'string' ? data.resolved_by : null;
    const resolution = typeof data?.resolution === 'string' ? data.resolution : null;
    const fromStatus = typeof data?.from === 'string' ? data.from : null;
    const toStatus = typeof data?.to === 'string' ? data.to : null;

    switch (e.type) {
      case 'host.heartbeat':
        return {
          title: 'Heartbeat',
          subtitle: groupName ?? hostId ?? 'host',
          href: hostId ? resolve(`/hosts/${hostId}`) : null,
        };
      case 'host.status_change':
        return {
          title: `Host ${toStatus ?? 'changed'}`,
          subtitle: `${fromStatus ?? '?'} → ${toStatus ?? '?'}`,
          href: hostId ? resolve(`/hosts/${hostId}`) : null,
        };
      case 'command.issued':
        return {
          title: 'Command issued',
          subtitle: issuedBy ? `by ${issuedBy}` : (commandId ?? ''),
          href: commandId ? resolve(`/commands/${commandId}`) : null,
        };
      case 'command.status_change':
        return {
          title: `Command ${status ?? 'updated'}`,
          subtitle: commandId ?? '',
          href: commandId ? resolve(`/commands/${commandId}`) : null,
        };
      case 'approval.created':
        return {
          title: 'Approval requested',
          subtitle: issuedBy ? `by ${issuedBy}` : (commandId ?? ''),
          href: resolve('/approvals'),
        };
      case 'approval.resolved':
        return {
          title: `Approval ${resolution ?? 'resolved'}`,
          subtitle: resolvedBy ? `by ${resolvedBy}` : (commandId ?? ''),
          href: commandId ? resolve(`/commands/${commandId}`) : resolve('/approvals'),
        };
      default:
        return { title: e.type, subtitle: '', href: null };
    }
  }

  // Newest first, capped at VISIBLE_LIMIT.
  const visible = $derived.by<readonly SseEvent[]>(() => {
    const arr = live?.events ?? [];
    return arr.slice().reverse().slice(0, VISIBLE_LIMIT);
  });

  const unreadCount = $derived.by(() => {
    if (!live) return 0;
    let count = 0;
    for (const e of live.events) {
      if (e.ts > lastSeenTs) count += 1;
    }
    return count;
  });

  const badgeLabel = $derived(unreadCount > 9 ? '9+' : String(unreadCount));

  function toggle(): void {
    open = !open;
    if (open) {
      // Mark everything as read at open-time. We capture the newest ts
      // we currently have so events arriving *after* the open still
      // show as unread once the user closes again.
      const newest = live?.events.length ? (live.events[live.events.length - 1]?.ts ?? 0) : 0;
      persistLastSeen(Math.max(lastSeenTs, newest, Date.now()));
    }
  }

  function close(): void {
    open = false;
  }

  function activate(e: SseEvent): void {
    const { href } = describe(e);
    close();
    if (href) {
      // The `href` is always produced via `resolve()` above.
      // eslint-disable-next-line svelte/no-navigation-without-resolve
      void goto(href as `/${string}`);
    }
  }

  function onDocumentClick(e: MouseEvent): void {
    if (!open) return;
    const target = e.target as Node | null;
    if (target && rootEl && !rootEl.contains(target)) {
      close();
    }
  }

  function onDocumentKey(e: KeyboardEvent): void {
    if (e.key === 'Escape' && open) close();
  }

  $effect(() => {
    if (!open) return;
    document.addEventListener('mousedown', onDocumentClick);
    document.addEventListener('keydown', onDocumentKey);
    return () => {
      document.removeEventListener('mousedown', onDocumentClick);
      document.removeEventListener('keydown', onDocumentKey);
    };
  });
</script>

{#if live}
  <div bind:this={rootEl} class="relative">
    <button
      type="button"
      class={cn(
        'touch-target relative inline-flex size-8 items-center justify-center rounded-md text-muted',
        'transition-colors hover:bg-subtle hover:text-default focus:outline-none',
        'focus-visible:ring-2 focus-visible:ring-accent',
      )}
      aria-label={unreadCount > 0 ? `Recent activity — ${unreadCount} unread` : 'Recent activity'}
      aria-haspopup="menu"
      aria-expanded={open}
      data-testid="activity-trigger"
      onclick={toggle}
    >
      <Bell class="size-4" aria-hidden="true" />
      {#if unreadCount > 0}
        <span
          class={cn(
            'absolute -right-1 -top-1 inline-flex h-4 min-w-[1rem] items-center justify-center',
            'rounded-full bg-danger px-1 font-mono text-[10px] font-semibold leading-none text-white',
          )}
          aria-hidden="true"
          data-testid="activity-badge"
        >
          {badgeLabel}
        </span>
      {/if}
    </button>

    {#if open}
      <div
        class={cn(
          'absolute right-0 z-40 mt-2 w-80 max-w-[calc(100vw-2rem)] overflow-hidden',
          'rounded-md border border-border-default bg-base shadow-lg',
        )}
        role="menu"
        aria-label="Recent activity"
        data-testid="activity-popover"
      >
        <div class="flex items-center justify-between border-b border-border-subtle px-3 py-2">
          <span class="text-sm font-semibold">Recent activity</span>
          <span class="text-xs text-muted">
            {visible.length} event{visible.length === 1 ? '' : 's'}
          </span>
        </div>
        {#if visible.length === 0}
          <div class="px-3 py-6 text-center text-sm text-muted" data-testid="activity-empty">
            {#if live.state === 'failed'}
              Real-time disconnected. Refresh to reconnect.
            {:else}
              All caught up.
            {/if}
          </div>
        {:else}
          <ul class="max-h-96 divide-y divide-border-subtle overflow-y-auto">
            {#each visible as evt, idx (evt.ts + ':' + idx)}
              {@const meta = describe(evt)}
              {@const isUnread = evt.ts > lastSeenTs}
              <li>
                <button
                  type="button"
                  class={cn(
                    'flex w-full items-start gap-2 px-3 py-2 text-left text-sm transition-colors',
                    'hover:bg-subtle focus:bg-subtle focus:outline-none',
                    isUnread && 'bg-subtle/50',
                  )}
                  data-testid="activity-item"
                  data-event-type={evt.type}
                  onclick={() => activate(evt)}
                >
                  <span
                    class={cn(
                      'mt-1.5 inline-block size-1.5 shrink-0 rounded-full',
                      isUnread ? 'bg-accent' : 'bg-transparent',
                    )}
                    aria-hidden="true"
                  ></span>
                  <span class="flex min-w-0 flex-1 flex-col">
                    <span class="flex items-baseline justify-between gap-2">
                      <span class="truncate font-medium text-default">{meta.title}</span>
                      <RelativeTime
                        iso={new Date(evt.ts).toISOString()}
                        class="shrink-0 text-[10px] text-muted"
                      />
                    </span>
                    {#if meta.subtitle}
                      <span class="truncate text-xs text-muted">{meta.subtitle}</span>
                    {/if}
                  </span>
                </button>
              </li>
            {/each}
          </ul>
        {/if}
      </div>
    {/if}
  </div>
{/if}
