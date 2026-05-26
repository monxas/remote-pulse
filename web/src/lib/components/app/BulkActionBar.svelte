<script lang="ts">
  import { Terminal, X } from '@lucide/svelte';
  import { Button } from '$lib/components/ui/button';
  import { Badge } from '$lib/components/ui/badge';

  /**
   * Floating action bar shown when the user has selected one or more hosts
   * in the Fleet table. Mirrors the affordance pattern used by Linear /
   * GitHub: stays out of the way until a selection exists, then anchors
   * to the bottom of the viewport with the most common bulk actions.
   *
   * The bar is presentational — it does not own selection state, just
   * receives the count + a list of hostname labels to surface and emits
   * intent events back to the parent (`onIssue`, `onClear`).
   */

  type Props = {
    count: number;
    /** Short hostnames shown as preview chips; the parent slices this list. */
    previewLabels: ReadonlyArray<string>;
    /** True total for the "+N more" affordance. */
    totalLabels: number;
    onIssue: () => void;
    onClear: () => void;
  };

  const { count, previewLabels, totalLabels, onIssue, onClear }: Props = $props();

  const extra = $derived(Math.max(0, totalLabels - previewLabels.length));
</script>

{#if count > 0}
  <div
    class="fixed inset-x-0 bottom-4 z-40 flex justify-center px-4 pb-safe sm:bottom-6"
    data-testid="bulk-action-bar"
    role="region"
    aria-label={`Bulk actions: ${count} hosts selected`}
  >
    <div
      class="flex min-h-14 w-full max-w-3xl items-center gap-3 rounded-full border border-border-default bg-elevated px-3 py-2 shadow-lg backdrop-blur"
    >
      <span class="flex items-center gap-2 text-sm" aria-live="polite">
        <Badge variant="default" class="font-mono">{count}</Badge>
        <span class="hidden sm:inline">hosts selected</span>
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

      <div class="ml-auto flex items-center gap-2">
        <Button size="sm" onclick={onIssue} data-testid="bulk-issue-command">
          <Terminal class="size-4" aria-hidden="true" />
          <span>Issue command</span>
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onclick={onClear}
          aria-label="Clear selection"
          data-testid="bulk-clear-selection"
        >
          <X class="size-4" aria-hidden="true" />
          <span class="hidden sm:inline">Clear</span>
        </Button>
      </div>
    </div>
  </div>
{/if}
