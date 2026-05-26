<script lang="ts">
  import { Loader2, ArrowDown } from '@lucide/svelte';
  import type { Snippet } from 'svelte';
  import { cn } from '$lib/utils';
  import {
    ptrStateFor,
    damp,
    PTR_ACTIVATE_PX,
    PTR_MAX_PX,
    PTR_TRIGGER_PX,
  } from './pull-to-refresh-state';

  /**
   * Pull-to-refresh wrapper. Activates only on coarse-pointer devices
   * (so mouse/trackpad scrolling never triggers it) and only when the
   * page's scroll position is at the top — otherwise we'd hijack the
   * native overscroll behaviour deeper in the content.
   *
   * Usage:
   *
   * ```svelte
   * <PullToRefresh onRefresh={() => $query.refetch()}>
   *   <SomeList />
   * </PullToRefresh>
   * ```
   *
   * Implementation notes:
   *
   *   - We track `touchstart`/`touchmove`/`touchend` on the wrapper.
   *   - To respect iOS Safari's rubber-band, we only start pulling
   *     when `window.scrollY === 0` AND the user is dragging DOWN.
   *   - `damp()` (in `pull-to-refresh-state.ts`) makes the indicator
   *     feel "heavier" past the trigger threshold (sqrt-style) — the
   *     same trick Mail / Twitter use.
   *   - Pure state helpers live in `pull-to-refresh-state.ts` so they
   *     are easy to unit-test without a Svelte/jsdom compile.
   */

  type Props = {
    onRefresh: () => Promise<unknown> | unknown;
    /** Disable the gesture without unmounting the wrapper. */
    disabled?: boolean;
    children: Snippet;
  };
  const { onRefresh, disabled = false, children }: Props = $props();

  let startY = $state(0);
  let distance = $state(0);
  let active = $state(false);
  let refreshing = $state(false);

  const visualState = $derived(ptrStateFor(distance, refreshing));
  const progress = $derived(Math.min(1, distance / PTR_TRIGGER_PX));

  function isCoarsePointer(): boolean {
    if (typeof window === 'undefined' || !window.matchMedia) return false;
    return window.matchMedia('(hover: none) and (pointer: coarse)').matches;
  }

  function onTouchStart(ev: TouchEvent): void {
    if (disabled || refreshing) return;
    if (!isCoarsePointer()) return;
    if (window.scrollY > 0) return;
    if (ev.touches.length !== 1) return;
    const t = ev.touches.item(0);
    if (t === null) return;
    startY = t.clientY;
    active = false;
    distance = 0;
  }

  function onTouchMove(ev: TouchEvent): void {
    if (disabled || refreshing) return;
    if (ev.touches.length !== 1) return;
    if (startY === 0) return;
    const t = ev.touches.item(0);
    if (t === null) return;
    const dy = t.clientY - startY;
    if (dy <= 0) {
      active = false;
      distance = 0;
      return;
    }
    if (window.scrollY > 0) {
      active = false;
      distance = 0;
      return;
    }
    if (dy > PTR_ACTIVATE_PX) {
      active = true;
      distance = Math.min(PTR_MAX_PX, damp(dy));
      if (ev.cancelable) ev.preventDefault();
    }
  }

  async function onTouchEnd(): Promise<void> {
    if (disabled) return;
    if (!active) {
      startY = 0;
      distance = 0;
      return;
    }
    const committed = distance >= PTR_TRIGGER_PX;
    active = false;
    startY = 0;
    if (committed) {
      refreshing = true;
      try {
        await onRefresh();
      } finally {
        refreshing = false;
        distance = 0;
      }
    } else {
      distance = 0;
    }
  }
</script>

<!--
  Touch handlers below are gesture hooks for the whole content
  region, not semantic actions. Every interactive child (rows,
  buttons, links) keeps its native role + keyboard accessibility,
  so the wrapper has no role of its own.
-->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="relative"
  style:overscroll-behavior-y="contain"
  style:touch-action="pan-y"
  ontouchstart={onTouchStart}
  ontouchmove={onTouchMove}
  ontouchend={onTouchEnd}
  ontouchcancel={onTouchEnd}
  data-testid="ptr-wrapper"
  data-ptr-state={visualState}
>
  {#if distance > 0 || refreshing}
    <div
      class="pointer-events-none absolute inset-x-0 top-0 z-20 flex items-center justify-center"
      style:transform="translateY({Math.max(0, distance - 24)}px)"
      style:opacity={Math.min(1, progress + (refreshing ? 1 : 0))}
      aria-live="polite"
      aria-busy={refreshing}
    >
      <div
        class="flex items-center gap-2 rounded-full border border-border-default bg-elevated px-3 py-1.5 text-xs text-muted shadow-sm"
      >
        {#if refreshing}
          <Loader2 class="size-4 animate-spin" aria-hidden="true" />
          <span>Refreshing…</span>
        {:else if visualState === 'ready'}
          <ArrowDown class="size-4 rotate-180" aria-hidden="true" />
          <span>Release to refresh</span>
        {:else}
          <span
            class="inline-flex"
            style:transform="rotate({progress * 180}deg)"
            style:transition="transform 80ms linear"
          >
            <ArrowDown class={cn('size-4')} aria-hidden="true" />
          </span>
          <span>Pull to refresh</span>
        {/if}
      </div>
    </div>
  {/if}
  {@render children()}
</div>
