<script lang="ts">
  /**
   * SavedViewsSwitcher — named-preset picker for any URL-state-driven page.
   *
   * Layout (per the design note):
   *   ┌─ Factory pill row ────────────────────────┐ ← built-in defaults
   *   │ [Default] [Today] [Last 7d] [Settings…]   │   always visible
   *   └───────────────────────────────────────────┘
   *   ┌─ Custom switcher (dropdown) ──────────────┐
   *   │ ▼ My audit · 24h │ [Save as…] [Manage]    │
   *   └───────────────────────────────────────────┘
   *
   * The pill row keeps the most common quick-filters one click away while
   * the dropdown holds user-saved views (which can grow unbounded) plus
   * the destructive actions (Save / Manage). When the URL params don't
   * match any view, the active label shows `Modified` and a `Discard`
   * pill appears next to it.
   */
  import {
    Bookmark,
    BookmarkPlus,
    ChevronDown,
    Pin,
    Trash2,
    Upload,
    Download,
    X,
    Check,
  } from '@lucide/svelte';
  import { page } from '$app/state';
  import { Button } from '$lib/components/ui/button';
  import { Input } from '$lib/components/ui/input';
  import { Badge } from '$lib/components/ui/badge';
  import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogDescription,
    DialogFooter,
  } from '$lib/components/ui/dialog';
  import { cn } from '$lib/utils';
  import { createSavedViewsStore, type SavedView } from './saved-views.svelte';

  type Props = {
    /** Scope key — `fleet`, `audit`, `commands`, etc. */
    scope: string;
    /** Pathname for `applyView` navigation. Defaults to the current page. */
    pathname?: string;
  };
  const { scope, pathname }: Props = $props();

  // The store binds to its scope/pathname for the component lifetime —
  // callers never swap these props mid-flight (each route mounts its own
  // switcher). Silence Svelte's "state_referenced_locally" warning that
  // applies to props passed into reactive code.
  // svelte-ignore state_referenced_locally
  const store = createSavedViewsStore(scope, pathname ?? page.url.pathname);

  // ── Dropdown state ────────────────────────────────────────────────
  let dropdownOpen = $state(false);
  function toggleDropdown(): void {
    dropdownOpen = !dropdownOpen;
  }
  function closeDropdown(): void {
    dropdownOpen = false;
  }

  // ── Save-as modal ─────────────────────────────────────────────────
  let saveOpen = $state(false);
  let saveName = $state('');
  let savePinned = $state(false);
  let saveError = $state<string | null>(null);

  function openSave(): void {
    saveName = '';
    savePinned = false;
    saveError = null;
    saveOpen = true;
    closeDropdown();
  }

  function commitSave(): void {
    const result = store.saveCurrent(saveName, { pinned: savePinned });
    if (result.ok) {
      saveOpen = false;
    } else {
      saveError =
        result.error === 'name-required'
          ? 'Please enter a name.'
          : 'A view with that name already exists.';
    }
  }

  // ── Manage modal ──────────────────────────────────────────────────
  let manageOpen = $state(false);
  let renamingId = $state<string | null>(null);
  let renameValue = $state('');
  let renameError = $state<string | null>(null);
  let importError = $state<string | null>(null);
  let importSummary = $state<string | null>(null);
  let fileInput: HTMLInputElement | null = $state(null);

  function openManage(): void {
    manageOpen = true;
    renamingId = null;
    renameValue = '';
    renameError = null;
    importError = null;
    importSummary = null;
    closeDropdown();
  }

  function startRename(view: SavedView): void {
    renamingId = view.id;
    renameValue = view.name;
    renameError = null;
  }

  function commitRename(view: SavedView): void {
    const r = store.updateView(view.id, { name: renameValue });
    if (r.ok) {
      renamingId = null;
    } else {
      renameError =
        r.error === 'name-required' ? 'Name required.' : 'A view with that name already exists.';
    }
  }

  function togglePin(view: SavedView): void {
    store.updateView(view.id, { pinned: !view.pinned });
  }

  function remove(view: SavedView): void {
    store.deleteView(view.id);
  }

  // ── Export / import ──────────────────────────────────────────────
  function doExport(): void {
    const json = store.exportJSON();
    const blob = new Blob([json], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `rp-saved-views-${scope}-${new Date().toISOString().slice(0, 10)}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  function triggerImport(): void {
    fileInput?.click();
  }

  async function onFileChosen(e: Event): Promise<void> {
    const input = e.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    importError = null;
    importSummary = null;
    if (!file) return;
    try {
      const text = await file.text();
      const result = store.importJSON(text);
      if (result.error) {
        importError = result.error;
      } else {
        importSummary = `Imported ${result.imported}, skipped ${result.skipped} (duplicates).`;
      }
    } catch (err) {
      importError = (err as Error).message;
    } finally {
      // Allow re-importing the same file.
      input.value = '';
    }
  }

  // ── Derived UI state ──────────────────────────────────────────────
  const pinnedFactory = $derived(store.factoryViews.filter((v) => v.pinned));
  const otherFactory = $derived(store.factoryViews.filter((v) => !v.pinned));
  const pinnedUser = $derived(store.userViews.filter((v) => v.pinned));
  const otherUser = $derived(store.userViews.filter((v) => !v.pinned));

  const activeLabel = $derived.by(() => {
    if (store.active) return store.active.name;
    if (store.modified) return 'Modified';
    return 'Default view';
  });
</script>

<div class="space-y-2" data-testid="saved-views-switcher" data-scope={scope}>
  <!-- Factory pill row — always visible, single-click quick filters. -->
  <div class="flex flex-wrap items-center gap-1.5" role="group" aria-label="Quick views">
    <button
      type="button"
      class={cn(
        'inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-xs font-medium transition-colors',
        store.active === null && !store.modified
          ? 'border-accent-border bg-accent-bg text-accent-text'
          : 'border-border-default bg-elevated text-default hover:bg-subtle',
      )}
      data-testid="saved-views-default"
      onclick={() => store.applyDefault()}
    >
      Default
    </button>
    {#each pinnedFactory as v (v.id)}
      <button
        type="button"
        class={cn(
          'inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-xs font-medium transition-colors',
          store.active?.id === v.id
            ? 'border-accent-border bg-accent-bg text-accent-text'
            : 'border-border-default bg-elevated text-default hover:bg-subtle',
        )}
        data-testid={`saved-views-factory-${v.id}`}
        onclick={() => store.applyView(v)}
      >
        {v.name}
      </button>
    {/each}
    {#each otherFactory as v (v.id)}
      <button
        type="button"
        class={cn(
          'inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-xs font-medium transition-colors',
          store.active?.id === v.id
            ? 'border-accent-border bg-accent-bg text-accent-text'
            : 'border-border-default bg-elevated text-muted hover:bg-subtle hover:text-default',
        )}
        data-testid={`saved-views-factory-${v.id}`}
        onclick={() => store.applyView(v)}
      >
        {v.name}
      </button>
    {/each}
  </div>

  <!-- Custom switcher: dropdown + save/manage actions. -->
  <div class="flex flex-wrap items-center gap-2">
    <div class="relative">
      <Button
        type="button"
        variant="outline"
        size="sm"
        onclick={toggleDropdown}
        aria-haspopup="menu"
        aria-expanded={dropdownOpen}
        data-testid="saved-views-trigger"
      >
        <Bookmark class="size-3.5" aria-hidden="true" />
        <span class="max-w-[14rem] truncate">{activeLabel}</span>
        {#if store.modified}
          <Badge variant="warn" class="ml-1">Modified</Badge>
        {/if}
        <ChevronDown class="size-3.5" aria-hidden="true" />
      </Button>
      {#if dropdownOpen}
        <!-- Click-away handler. -->
        <button
          type="button"
          class="fixed inset-0 z-10 cursor-default"
          aria-hidden="true"
          tabindex="-1"
          onclick={closeDropdown}
        ></button>
        <div
          role="menu"
          class="absolute left-0 z-20 mt-1 min-w-[18rem] max-w-[24rem] overflow-hidden rounded-md border border-border-default bg-elevated shadow-lg"
        >
          <div class="max-h-72 overflow-auto py-1">
            <button
              type="button"
              role="menuitem"
              class={cn(
                'flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-subtle',
                store.active === null && !store.modified && 'bg-subtle',
              )}
              onclick={() => {
                store.applyDefault();
                closeDropdown();
              }}
            >
              <span class="flex-1 truncate">Default view</span>
              {#if store.active === null && !store.modified}
                <Check class="size-3.5 text-accent-text" aria-hidden="true" />
              {/if}
            </button>

            {#if pinnedUser.length > 0}
              <div class="px-3 py-1 text-[10px] font-semibold uppercase tracking-wide text-muted">
                Pinned
              </div>
              {#each pinnedUser as v (v.id)}
                <button
                  type="button"
                  role="menuitem"
                  class={cn(
                    'flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-subtle',
                    store.active?.id === v.id && 'bg-subtle',
                  )}
                  data-testid={`saved-views-item-${v.id}`}
                  onclick={() => {
                    store.applyView(v);
                    closeDropdown();
                  }}
                >
                  <Pin class="size-3 text-muted" aria-hidden="true" />
                  <span class="flex-1 truncate">{v.name}</span>
                  {#if store.active?.id === v.id}
                    <Check class="size-3.5 text-accent-text" aria-hidden="true" />
                  {/if}
                </button>
              {/each}
            {/if}

            {#if otherUser.length > 0}
              <div class="px-3 py-1 text-[10px] font-semibold uppercase tracking-wide text-muted">
                Saved
              </div>
              {#each otherUser as v (v.id)}
                <button
                  type="button"
                  role="menuitem"
                  class={cn(
                    'flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-subtle',
                    store.active?.id === v.id && 'bg-subtle',
                  )}
                  data-testid={`saved-views-item-${v.id}`}
                  onclick={() => {
                    store.applyView(v);
                    closeDropdown();
                  }}
                >
                  <span class="flex-1 truncate">{v.name}</span>
                  {#if store.active?.id === v.id}
                    <Check class="size-3.5 text-accent-text" aria-hidden="true" />
                  {/if}
                </button>
              {/each}
            {/if}

            {#if pinnedUser.length === 0 && otherUser.length === 0}
              <div class="px-3 py-2 text-xs text-muted">No custom views yet.</div>
            {/if}
          </div>

          <div class="border-t border-border-default">
            <button
              type="button"
              role="menuitem"
              class="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-subtle"
              data-testid="saved-views-save"
              onclick={openSave}
            >
              <BookmarkPlus class="size-3.5" aria-hidden="true" />
              Save current as view…
            </button>
            <button
              type="button"
              role="menuitem"
              class="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-subtle"
              data-testid="saved-views-manage"
              onclick={openManage}
            >
              <Bookmark class="size-3.5" aria-hidden="true" />
              Manage views…
            </button>
          </div>
        </div>
      {/if}
    </div>

    {#if store.modified}
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onclick={() => store.applyDefault()}
        data-testid="saved-views-discard"
      >
        <X class="size-3.5" aria-hidden="true" />
        Discard
      </Button>
      {#if store.active === null}
        <Button
          type="button"
          variant="outline"
          size="sm"
          onclick={openSave}
          data-testid="saved-views-save-changes"
        >
          <BookmarkPlus class="size-3.5" aria-hidden="true" />
          Save as view
        </Button>
      {/if}
    {/if}
  </div>
</div>

<!-- ─── Save modal ─────────────────────────────────────────────── -->
<Dialog bind:open={saveOpen}>
  <DialogContent>
    <DialogHeader>
      <DialogTitle>Save current view</DialogTitle>
      <DialogDescription>
        Capture the active filters as a named preset stored in this browser.
      </DialogDescription>
    </DialogHeader>
    <div class="space-y-3">
      <label class="block space-y-1">
        <span class="text-xs font-medium text-muted">Name</span>
        <Input
          bind:value={saveName}
          placeholder="My filters"
          autofocus
          data-testid="saved-views-save-name"
          onkeydown={(e: KeyboardEvent) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              commitSave();
            }
          }}
        />
      </label>
      <label class="flex items-center gap-2 text-sm">
        <input type="checkbox" bind:checked={savePinned} data-testid="saved-views-save-pinned" />
        <span>Pin to top of the list</span>
      </label>
      {#if saveError}
        <p class="text-xs text-danger-text" role="alert" data-testid="saved-views-save-error">
          {saveError}
        </p>
      {/if}
    </div>
    <DialogFooter>
      <Button variant="ghost" onclick={() => (saveOpen = false)}>Cancel</Button>
      <Button onclick={commitSave} data-testid="saved-views-save-submit">Save view</Button>
    </DialogFooter>
  </DialogContent>
</Dialog>

<!-- ─── Manage modal ──────────────────────────────────────────── -->
<Dialog bind:open={manageOpen}>
  <DialogContent class="max-w-lg">
    <DialogHeader>
      <DialogTitle>Manage saved views</DialogTitle>
      <DialogDescription>
        Rename, pin, or delete views. Factory defaults are shown but can't be edited.
      </DialogDescription>
    </DialogHeader>

    <div class="space-y-4">
      <section class="space-y-2">
        <h3 class="text-xs font-semibold uppercase tracking-wide text-muted">Custom</h3>
        {#if store.userViews.length === 0}
          <p class="text-xs text-muted">
            You haven't saved any custom views yet. Apply filters on the page, then choose “Save
            current as view…”.
          </p>
        {:else}
          <ul class="divide-y divide-border-subtle rounded-md border border-border-default">
            {#each store.userViews as v (v.id)}
              <li
                class="flex items-center gap-2 px-3 py-2"
                data-testid={`saved-views-manage-row-${v.id}`}
              >
                {#if renamingId === v.id}
                  <Input
                    bind:value={renameValue}
                    class="flex-1"
                    onkeydown={(e: KeyboardEvent) => {
                      if (e.key === 'Enter') commitRename(v);
                      if (e.key === 'Escape') renamingId = null;
                    }}
                  />
                  <Button size="sm" onclick={() => commitRename(v)}>Save</Button>
                  <Button size="sm" variant="ghost" onclick={() => (renamingId = null)}>
                    Cancel
                  </Button>
                {:else}
                  <button
                    type="button"
                    class="flex-1 truncate text-left text-sm hover:underline"
                    onclick={() => {
                      store.applyView(v);
                      manageOpen = false;
                    }}
                  >
                    {v.name}
                    {#if v.pinned}
                      <Badge variant="muted" class="ml-2">Pinned</Badge>
                    {/if}
                  </button>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label="Pin"
                    onclick={() => togglePin(v)}
                    data-testid={`saved-views-pin-${v.id}`}
                  >
                    <Pin class={cn('size-3.5', v.pinned && 'text-accent-text')} />
                  </Button>
                  <Button size="sm" variant="ghost" onclick={() => startRename(v)}>Rename</Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label="Delete"
                    onclick={() => remove(v)}
                    data-testid={`saved-views-delete-${v.id}`}
                  >
                    <Trash2 class="size-3.5 text-danger-text" />
                  </Button>
                {/if}
              </li>
            {/each}
          </ul>
        {/if}
        {#if renameError}
          <p class="text-xs text-danger-text" role="alert">{renameError}</p>
        {/if}
      </section>

      <section class="space-y-2">
        <h3 class="text-xs font-semibold uppercase tracking-wide text-muted">Factory defaults</h3>
        <ul class="space-y-1 text-sm text-muted">
          {#each store.factoryViews as v (v.id)}
            <li class="flex items-center justify-between">
              <span>{v.name}</span>
              <Badge variant="outline">default</Badge>
            </li>
          {/each}
        </ul>
      </section>

      <section class="space-y-2">
        <h3 class="text-xs font-semibold uppercase tracking-wide text-muted">Import / export</h3>
        <div class="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" onclick={doExport} data-testid="saved-views-export">
            <Download class="size-3.5" />
            Export JSON
          </Button>
          <Button
            size="sm"
            variant="outline"
            onclick={triggerImport}
            data-testid="saved-views-import"
          >
            <Upload class="size-3.5" />
            Import JSON
          </Button>
          <input
            bind:this={fileInput}
            type="file"
            accept="application/json,.json"
            class="hidden"
            onchange={onFileChosen}
            data-testid="saved-views-import-input"
          />
        </div>
        {#if importError}
          <p class="text-xs text-danger-text" role="alert">{importError}</p>
        {/if}
        {#if importSummary}
          <p class="text-xs text-success-text" role="status">{importSummary}</p>
        {/if}
      </section>
    </div>

    <DialogFooter>
      <Button onclick={() => (manageOpen = false)}>Done</Button>
    </DialogFooter>
  </DialogContent>
</Dialog>
