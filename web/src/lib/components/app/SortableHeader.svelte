<script lang="ts">
  /**
   * Clickable column header for sortable tables. Pairs with `createTableState`
   * (see `table-state.svelte.ts`). Emits `aria-sort` so screen readers
   * announce the current state, and renders chevron icons that mirror the
   * sort direction.
   *
   * Click cycle: unsorted → asc → desc → unsorted.
   */
  import type { Snippet } from 'svelte';
  import { ChevronDown, ChevronUp, ChevronsUpDown } from '@lucide/svelte';
  import { cn } from '$lib/utils';

  type SortDir = 'asc' | 'desc' | null;

  type Props = {
    /** Column key — must match the one passed to `tableState.toggleSort()`. */
    columnKey: string;
    /** Active sort key on the table (or null when unsorted). */
    activeKey: string | null;
    /** Active sort direction. */
    activeDir: SortDir;
    /** Click handler — should call `tableState.toggleSort(columnKey)`. */
    onToggle: (key: string) => void;
    /** Cell alignment: text-left | text-right | text-center. */
    align?: 'left' | 'right' | 'center';
    /** Extra class for the `<th>`. */
    class?: string;
    /** Label content (usually plain text). */
    children: Snippet;
  };

  const {
    columnKey,
    activeKey,
    activeDir,
    onToggle,
    align = 'left',
    class: className,
    children,
  }: Props = $props();

  const isActive = $derived(activeKey === columnKey);
  const sortState = $derived<'ascending' | 'descending' | 'none'>(
    isActive && activeDir ? (activeDir === 'asc' ? 'ascending' : 'descending') : 'none',
  );

  const alignClass = $derived(
    align === 'right' ? 'text-right' : align === 'center' ? 'text-center' : 'text-left',
  );
</script>

<th scope="col" aria-sort={sortState} class={cn('px-3 py-2 font-medium', alignClass, className)}>
  <button
    type="button"
    onclick={() => onToggle(columnKey)}
    class={cn(
      'group inline-flex items-center gap-1 rounded text-inherit uppercase',
      'transition-colors hover:text-default',
      'focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
      align === 'right' && 'ml-auto flex-row-reverse',
      align === 'center' && 'mx-auto',
    )}
  >
    {@render children()}
    {#if isActive && activeDir === 'asc'}
      <ChevronUp class="size-3.5 text-default" aria-hidden="true" />
    {:else if isActive && activeDir === 'desc'}
      <ChevronDown class="size-3.5 text-default" aria-hidden="true" />
    {:else}
      <ChevronsUpDown
        class="size-3.5 opacity-40 transition-opacity group-hover:opacity-80"
        aria-hidden="true"
      />
    {/if}
  </button>
</th>
