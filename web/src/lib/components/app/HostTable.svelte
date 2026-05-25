<script lang="ts">
  import { goto } from '$app/navigation';
  import { resolve } from '$app/paths';
  import type { HostSummary } from '$lib/api';
  import HostStatusBadge from './HostStatusBadge.svelte';
  import Sparkline from './Sparkline.svelte';
  import RelativeTime from './RelativeTime.svelte';

  type Props = { hosts: ReadonlyArray<HostSummary> };
  const { hosts }: Props = $props();

  function navigate(id: string): void {
    void goto(resolve('/hosts/[id]', { id }));
  }

  function onKey(ev: KeyboardEvent, id: string): void {
    if (ev.key === 'Enter' || ev.key === ' ') {
      ev.preventDefault();
      navigate(id);
    }
  }

  function fmtPct(v: number | null): string {
    return v === null || v === undefined ? '—' : `${v.toFixed(0)}%`;
  }
</script>

<!-- Desktop / tablet table -->
<div class="hidden overflow-hidden rounded-lg border border-border-default sm:block">
  <table class="w-full border-collapse text-sm">
    <thead class="bg-subtle text-xs tracking-wide text-muted uppercase">
      <tr>
        <th scope="col" class="px-3 py-2 text-left font-medium">Host</th>
        <th scope="col" class="px-3 py-2 text-left font-medium">Group</th>
        <th scope="col" class="px-3 py-2 text-left font-medium">Status</th>
        <th scope="col" class="px-3 py-2 text-left font-medium">CPU</th>
        <th scope="col" class="px-3 py-2 text-left font-medium">Memory</th>
        <th scope="col" class="px-3 py-2 text-right font-medium">Last seen</th>
      </tr>
    </thead>
    <tbody>
      {#each hosts as host (host.id)}
        <tr
          class="cursor-pointer border-t border-border-subtle transition-colors hover:bg-hover focus-within:bg-hover"
          tabindex="0"
          role="link"
          aria-label={`Open host ${host.hostname}`}
          onclick={() => navigate(host.id)}
          onkeydown={(e) => onKey(e, host.id)}
        >
          <td class="px-3 py-2">
            <span class="font-mono text-sm font-medium text-default">{host.hostname}</span>
          </td>
          <td class="px-3 py-2 text-muted">{host.group_name}</td>
          <td class="px-3 py-2">
            <HostStatusBadge status={host.status} lastSeenSecondsAgo={host.last_seen_seconds_ago} />
          </td>
          <td class="px-3 py-2">
            <div class="flex items-center gap-3">
              <Sparkline
                data={{ ts: host.sparkline.ts, values: host.sparkline.cpu_pct }}
                width={100}
                height={28}
                color="var(--accent-solid)"
                title="CPU"
                unit="%"
              />
              <span class="font-mono text-xs text-muted">{fmtPct(host.current.cpu_pct)}</span>
            </div>
          </td>
          <td class="px-3 py-2">
            <div class="flex items-center gap-3">
              <Sparkline
                data={{ ts: host.sparkline.ts, values: host.sparkline.mem_pct }}
                width={100}
                height={28}
                color="var(--warn-solid)"
                title="Memory"
                unit="%"
              />
              <span class="font-mono text-xs text-muted">{fmtPct(host.current.mem_pct)}</span>
            </div>
          </td>
          <td class="px-3 py-2 text-right">
            <RelativeTime
              iso={host.last_seen_at}
              secondsAgo={host.last_seen_seconds_ago}
              class="font-mono text-xs text-muted"
            />
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
</div>

<!-- Mobile card list -->
<ul class="space-y-2 sm:hidden">
  {#each hosts as host (host.id)}
    <li>
      <button
        type="button"
        class="w-full rounded-lg border border-border-default bg-elevated p-3 text-left transition-colors hover:bg-hover focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        onclick={() => navigate(host.id)}
      >
        <div class="flex items-center justify-between">
          <span class="font-mono text-sm font-medium text-default">{host.hostname}</span>
          <HostStatusBadge
            status={host.status}
            lastSeenSecondsAgo={host.last_seen_seconds_ago}
            showLabel={false}
          />
        </div>
        <div class="mt-1 flex items-center justify-between text-xs text-muted">
          <span>{host.group_name}</span>
          <span class="font-mono">CPU {fmtPct(host.current.cpu_pct)}</span>
        </div>
        <div class="mt-1 text-right text-[10px] text-muted">
          <RelativeTime
            iso={host.last_seen_at}
            secondsAgo={host.last_seen_seconds_ago}
            class="font-mono"
          />
        </div>
      </button>
    </li>
  {/each}
</ul>
