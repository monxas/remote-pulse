<script lang="ts">
  import { Trash2, X } from '@lucide/svelte';
  import { Button } from '$lib/components/ui/button';
  import { Badge } from '$lib/components/ui/badge';

  /**
   * Floating action bar for the Settings → Groups tab. Only exposes
   * bulk delete since rename in bulk doesn't make UX sense and group
   * membership is driven from the user side. Bulk delete requires every
   * selected group to have `host_count === 0` — the parent enforces
   * that pre-filter and the button surfaces a hint otherwise.
   */

  type Props = {
    count: number;
    previewLabels: ReadonlyArray<string>;
    totalLabels: number;
    /** True when every selected group is safely deletable (no hosts). */
    deletable: boolean;
    /** Names of groups still holding hosts (for the hint copy). */
    blockedNames: ReadonlyArray<string>;
    onDelete: () => void;
    onClear: () => void;
  };

  const { count, previewLabels, totalLabels, deletable, blockedNames, onDelete, onClear }: Props =
    $props();

  const extra = $derived(Math.max(0, totalLabels - previewLabels.length));
</script>

{#if count > 0}
  <div
    class="fixed inset-x-0 bottom-4 z-40 flex justify-center px-4 sm:bottom-6"
    data-testid="bulk-group-action-bar"
    role="region"
    aria-label={`Bulk actions: ${count} groups selected`}
  >
    <div
      class="flex w-full max-w-3xl flex-wrap items-center gap-2 rounded-2xl border border-border-default bg-elevated px-3 py-2 shadow-lg backdrop-blur"
    >
      <span class="flex items-center gap-2 text-sm" aria-live="polite">
        <Badge variant="default" class="font-mono">{count}</Badge>
        <span class="hidden sm:inline">groups selected</span>
      </span>

      <span class="hidden flex-1 truncate text-xs text-muted md:inline" aria-hidden="true">
        {#each previewLabels as label, i (label)}
          <span class="font-mono">{label}</span>{#if i < previewLabels.length - 1}<span
              >,
            </span>{/if}
        {/each}
        {#if extra > 0}<span> +{extra} more</span>{/if}
      </span>

      {#if !deletable && blockedNames.length > 0}
        <span class="text-xs text-warn-text" data-testid="bulk-group-blocked">
          {blockedNames.length} group{blockedNames.length === 1 ? '' : 's'} still hold hosts.
        </span>
      {/if}

      <div class="ml-auto flex items-center gap-2">
        <Button
          size="sm"
          variant="danger"
          onclick={onDelete}
          disabled={!deletable}
          data-testid="bulk-delete-groups"
          title={deletable
            ? 'Delete selected groups'
            : 'Reassign or remove hosts from the blocked groups first'}
        >
          <Trash2 class="size-4" aria-hidden="true" />
          <span class="hidden sm:inline">Delete</span>
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onclick={onClear}
          aria-label="Clear selection"
          data-testid="bulk-group-clear-selection"
        >
          <X class="size-4" aria-hidden="true" />
        </Button>
      </div>
    </div>
  </div>
{/if}
