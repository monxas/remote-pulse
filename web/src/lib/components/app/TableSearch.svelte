<script lang="ts">
  /**
   * Debounced search input + reset button for tables backed by `createTableState`.
   *
   * Decoupled from the state object so the same UI can be reused for any
   * table on the page; the caller wires `value`/`onChange` against the
   * `tableState.query`/`tableState.setQuery()` API.
   */
  import { Search, X } from '@lucide/svelte';
  import { Input } from '$lib/components/ui/input';
  import { Button } from '$lib/components/ui/button';

  type Props = {
    /** Current query value (read from `tableState.query`). */
    value: string;
    /** Set the URL-persisted query — typically `tableState.setQuery`. */
    onChange: (q: string) => void;
    /** Reset handler — typically `tableState.reset`. */
    onReset: () => void;
    placeholder?: string;
    /** Show the reset button (e.g. when sort or query is non-default). */
    showReset?: boolean;
    /** aria-label / data-testid namespace. */
    label?: string;
    testId?: string;
  };

  const {
    value,
    onChange,
    onReset,
    placeholder = 'Search…',
    showReset = false,
    label = 'Search rows',
    testId,
  }: Props = $props();

  // Local state so the input doesn't flicker between keystrokes — we debounce
  // the URL update to keep router churn off the keyboard hot path. We
  // initialise to `''` and let the effect below mirror `value` in once
  // the component is mounted (avoids the `state_referenced_locally` warn).
  let local = $state('');
  $effect(() => {
    local = value;
  });

  let debounceTimer: ReturnType<typeof setTimeout> | null = null;

  function onInput(ev: Event): void {
    local = (ev.target as HTMLInputElement).value;
    if (debounceTimer !== null) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => onChange(local), 200);
  }

  function reset(): void {
    if (debounceTimer !== null) clearTimeout(debounceTimer);
    local = '';
    onReset();
  }
</script>

<div class="flex items-center gap-2">
  <div class="relative flex-1">
    <Search
      class="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted"
      aria-hidden="true"
    />
    <Input
      value={local}
      oninput={onInput}
      {placeholder}
      class="pl-8"
      aria-label={label}
      data-testid={testId ? `${testId}-input` : undefined}
    />
  </div>
  {#if showReset}
    <Button
      type="button"
      variant="ghost"
      size="sm"
      onclick={reset}
      data-testid={testId ? `${testId}-reset` : undefined}
    >
      <X class="mr-1 size-4" aria-hidden="true" />
      Reset
    </Button>
  {/if}
</div>
