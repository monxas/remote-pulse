<script lang="ts">
  import { goto } from '$app/navigation';
  import { resolve } from '$app/paths';
  import type { HostSummary } from '$lib/api';
  import HostStatusBadge from './HostStatusBadge.svelte';
  import Sparkline from './Sparkline.svelte';
  import RelativeTime from './RelativeTime.svelte';
  import SortableHeader from './SortableHeader.svelte';
  import { createTableState } from './table-state.svelte';
  import type { IHostSelection } from './host-selection.svelte';

  type Props = {
    hosts: ReadonlyArray<HostSummary>;
    /**
     * Optional multi-select handle. When provided, the table renders a
     * checkbox column + a tri-state header checkbox bound to this
     * selection. When omitted, the table is read-only (back-compat for
     * callers that don't need bulk actions).
     */
    selection?: IHostSelection;
  };
  const { hosts, selection }: Props = $props();

  // Default order: server returns hosts sorted by last_seen DESC. We respect
  // that whenever the user hasn't picked a column; once they click a header,
  // we sort in the browser on the current page of results (the server
  // pagination cursor isn't exposed yet, so client-side sort matches scope).
  const table = createTableState<HostSummary>(() => hosts, {
    prefix: 'h_',
    searchable: ['hostname', 'group_name'],
    getSortValue: (row, key) => {
      switch (key) {
        case 'hostname':
          return row.hostname;
        case 'group_name':
          return row.group_name;
        case 'status':
          return row.status;
        case 'cpu':
          return row.current.cpu_pct ?? -1;
        case 'mem':
          return row.current.mem_pct ?? -1;
        case 'last_seen':
          // smaller seconds_ago = more recent; sort ascending puts freshest first
          return row.last_seen_seconds_ago ?? Number.MAX_SAFE_INTEGER;
        default:
          return (row as unknown as Record<string, unknown>)[key];
      }
    },
  });

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

  // Bind the header checkbox to the tri-state derived from the currently
  // sorted/filtered view — that way "Toggle all" matches what the user
  // actually sees, not the underlying unfiltered list.
  const visibleIds = $derived(table.view.map((h) => h.id));
  const allState = $derived(selection ? selection.selectAllState(visibleIds) : 'none');

  // The native HTML checkbox has no built-in indeterminate prop; we wire
  // it through a small `use:indeterminate` action so the DOM stays in
  // sync with the Svelte state without `bind:this` boilerplate.
  function indeterminate(node: HTMLInputElement, value: boolean) {
    node.indeterminate = value;
    return {
      update(next: boolean) {
        node.indeterminate = next;
      },
    };
  }

  function stop(ev: Event): void {
    // The row is clickable (navigates to /hosts/[id]). The checkbox
    // sits inside that row, so any pointer/keyboard event from the
    // checkbox must NOT bubble up and trigger navigation.
    ev.stopPropagation();
  }
</script>

<!-- Desktop / tablet table -->
<div class="hidden overflow-hidden rounded-lg border border-border-default sm:block">
  <table class="w-full border-collapse text-sm" data-testid="hosts-table">
    <thead class="bg-subtle text-xs tracking-wide text-muted uppercase">
      <tr>
        {#if selection}
          <th class="w-10 px-3 py-2 text-left" scope="col">
            <input
              type="checkbox"
              class="size-4 cursor-pointer accent-[var(--accent-solid)]"
              checked={allState === 'all'}
              use:indeterminate={allState === 'some'}
              onchange={() => selection?.toggleAllVisible(visibleIds)}
              onclick={stop}
              aria-label={allState === 'all'
                ? 'Deselect all visible hosts'
                : 'Select all visible hosts'}
              data-testid="select-all-hosts"
            />
          </th>
        {/if}
        <SortableHeader
          columnKey="hostname"
          activeKey={table.sortKey}
          activeDir={table.sortDir}
          onToggle={(k) => table.toggleSort(k)}
        >
          Host
        </SortableHeader>
        <SortableHeader
          columnKey="group_name"
          activeKey={table.sortKey}
          activeDir={table.sortDir}
          onToggle={(k) => table.toggleSort(k)}
        >
          Group
        </SortableHeader>
        <SortableHeader
          columnKey="status"
          activeKey={table.sortKey}
          activeDir={table.sortDir}
          onToggle={(k) => table.toggleSort(k)}
        >
          Status
        </SortableHeader>
        <SortableHeader
          columnKey="cpu"
          activeKey={table.sortKey}
          activeDir={table.sortDir}
          onToggle={(k) => table.toggleSort(k)}
        >
          CPU
        </SortableHeader>
        <SortableHeader
          columnKey="mem"
          activeKey={table.sortKey}
          activeDir={table.sortDir}
          onToggle={(k) => table.toggleSort(k)}
        >
          Memory
        </SortableHeader>
        <SortableHeader
          columnKey="last_seen"
          activeKey={table.sortKey}
          activeDir={table.sortDir}
          onToggle={(k) => table.toggleSort(k)}
          align="right"
        >
          Last seen
        </SortableHeader>
      </tr>
    </thead>
    <tbody>
      {#each table.view as host (host.id)}
        <tr
          class="cursor-pointer border-t border-border-subtle transition-colors hover:bg-hover focus-within:bg-hover"
          tabindex="0"
          role="link"
          aria-label={`Open host ${host.hostname}`}
          onclick={() => navigate(host.id)}
          onkeydown={(e) => onKey(e, host.id)}
        >
          {#if selection}
            <td class="px-3 py-2">
              <input
                type="checkbox"
                class="size-4 cursor-pointer accent-[var(--accent-solid)]"
                checked={selection.has(host.id)}
                onchange={() => selection?.toggle(host.id)}
                onclick={stop}
                onkeydown={stop}
                aria-label={`Select host ${host.hostname}`}
                data-testid={`select-host-${host.hostname}`}
              />
            </td>
          {/if}
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
    <li class="relative">
      {#if selection}
        <input
          type="checkbox"
          class="absolute right-3 top-3 z-10 size-4 cursor-pointer accent-[var(--accent-solid)]"
          checked={selection.has(host.id)}
          onchange={() => selection?.toggle(host.id)}
          onclick={stop}
          aria-label={`Select host ${host.hostname}`}
          data-testid={`select-host-mobile-${host.hostname}`}
        />
      {/if}
      <button
        type="button"
        class="w-full rounded-lg border border-border-default bg-elevated p-3 text-left transition-colors hover:bg-hover focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        onclick={() => navigate(host.id)}
      >
        <div class="flex items-center justify-between {selection ? 'pr-7' : ''}">
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
