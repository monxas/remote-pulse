<script lang="ts">
  import { Trash2, Users as UsersIcon, FolderPlus, FolderMinus, KeyRound, X } from '@lucide/svelte';
  import { Button } from '$lib/components/ui/button';
  import { Badge } from '$lib/components/ui/badge';

  /**
   * Floating action bar shown when the user has selected one or more
   * dashboard users in the Settings → Users tab. Mirrors the visual
   * language of `BulkActionBar.svelte` but exposes the user-specific
   * actions: change role, add/remove group, grant permission, delete.
   *
   * Presentational only — emits intent events back to the parent which
   * wires the modals + bulk dispatcher.
   */

  type Props = {
    count: number;
    /** Short email previews. The parent slices to a sensible length. */
    previewLabels: ReadonlyArray<string>;
    totalLabels: number;
    onChangeRole: () => void;
    onAddGroup: () => void;
    onRemoveGroup: () => void;
    onGrant: () => void;
    onDelete: () => void;
    onClear: () => void;
  };

  const {
    count,
    previewLabels,
    totalLabels,
    onChangeRole,
    onAddGroup,
    onRemoveGroup,
    onGrant,
    onDelete,
    onClear,
  }: Props = $props();

  const extra = $derived(Math.max(0, totalLabels - previewLabels.length));
</script>

{#if count > 0}
  <div
    class="fixed inset-x-0 bottom-4 z-40 flex justify-center px-4 sm:bottom-6"
    data-testid="bulk-user-action-bar"
    role="region"
    aria-label={`Bulk actions: ${count} users selected`}
  >
    <div
      class="flex w-full max-w-4xl flex-wrap items-center gap-2 rounded-2xl border border-border-default bg-elevated px-3 py-2 shadow-lg backdrop-blur"
    >
      <span class="flex items-center gap-2 text-sm" aria-live="polite">
        <Badge variant="default" class="font-mono">{count}</Badge>
        <span class="hidden sm:inline">users selected</span>
        <span class="sm:hidden">selected</span>
      </span>

      <span class="hidden flex-1 truncate text-xs text-muted md:inline" aria-hidden="true">
        {#each previewLabels as label, i (label)}
          <span class="font-mono">{label}</span>{#if i < previewLabels.length - 1}<span
              >,
            </span>{/if}
        {/each}
        {#if extra > 0}<span> +{extra} more</span>{/if}
      </span>

      <div class="ml-auto flex flex-wrap items-center gap-2">
        <Button size="sm" variant="outline" onclick={onChangeRole} data-testid="bulk-change-role">
          <UsersIcon class="size-4" aria-hidden="true" />
          <span class="hidden sm:inline">Change role</span>
        </Button>
        <Button size="sm" variant="outline" onclick={onAddGroup} data-testid="bulk-add-group">
          <FolderPlus class="size-4" aria-hidden="true" />
          <span class="hidden sm:inline">Add to group</span>
        </Button>
        <Button size="sm" variant="outline" onclick={onRemoveGroup} data-testid="bulk-remove-group">
          <FolderMinus class="size-4" aria-hidden="true" />
          <span class="hidden sm:inline">Remove group</span>
        </Button>
        <Button size="sm" variant="outline" onclick={onGrant} data-testid="bulk-grant-permission">
          <KeyRound class="size-4" aria-hidden="true" />
          <span class="hidden sm:inline">Grant</span>
        </Button>
        <Button size="sm" variant="danger" onclick={onDelete} data-testid="bulk-delete-users">
          <Trash2 class="size-4" aria-hidden="true" />
          <span class="hidden sm:inline">Delete</span>
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onclick={onClear}
          aria-label="Clear selection"
          data-testid="bulk-user-clear-selection"
        >
          <X class="size-4" aria-hidden="true" />
        </Button>
      </div>
    </div>
  </div>
{/if}
