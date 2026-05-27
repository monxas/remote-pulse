<script lang="ts">
  /**
   * Headless dispatcher that bridges the SSE live stream to native browser
   * `Notification` objects when:
   *
   *  1. The browser supports the Notifications API.
   *  2. The user granted permission (Notification.permission === 'granted').
   *  3. The user opted in for this event category (Settings → Notifications).
   *  4. The dashboard tab is **not focused** — the focused case is already
   *     handled by LiveToasts.svelte with a non-disruptive sonner toast.
   *
   * The classify / decide / render pipeline is unit-tested in
   * `notifications-state.test.ts`; this component is the thin glue
   * (listener lifecycle + DOM access).
   *
   * No service worker, no VAPID push — this means notifications stop when
   * the user closes the tab. A future ADR can layer VAPID push on top
   * without touching this dispatcher (the opt-in persistence is shared).
   */
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { getLiveStream } from '$lib/queries/live-context';
  import { userStore } from '$lib/stores/user.svelte';
  import {
    DEFAULT_OPT_INS,
    classifySseEvent,
    loadOptIns,
    renderNotification,
    shouldFireNotification,
    type NotificationOptIns,
  } from './notifications-state';
  import type { SseEvent } from '$lib/queries/sse.svelte';

  const live = getLiveStream();

  /**
   * Read the freshest decision inputs at fire time rather than caching:
   * permission can be revoked at any time and the opt-in checkboxes can
   * change between events. The reads are cheap (synchronous property /
   * localStorage lookups).
   */
  function currentPermission(): 'default' | 'granted' | 'denied' | 'unsupported' {
    if (typeof window === 'undefined' || !('Notification' in window)) return 'unsupported';
    return Notification.permission;
  }

  function currentOptIns(): NotificationOptIns {
    if (typeof window === 'undefined') return { ...DEFAULT_OPT_INS };
    try {
      return loadOptIns(window.localStorage, userStore.value?.user_email ?? null);
    } catch {
      return { ...DEFAULT_OPT_INS };
    }
  }

  function isTabFocused(): boolean {
    if (typeof document === 'undefined') return true;
    // `hasFocus` is the most reliable signal across browsers; `visibilityState`
    // also flips to 'hidden' when the tab is backgrounded which is what we want.
    return document.visibilityState === 'visible' && document.hasFocus();
  }

  function handle(evt: SseEvent): void {
    if (typeof window === 'undefined' || !('Notification' in window)) return;

    const eventType = classifySseEvent(evt.type, evt.data);
    if (!eventType) return;

    const decision = shouldFireNotification({
      eventType,
      optIns: currentOptIns(),
      permission: currentPermission(),
      isTabFocused: isTabFocused(),
      userRole: userStore.value?.user_role ?? null,
    });
    if (!decision) return;

    const content = renderNotification(eventType, evt.data, evt.id ?? null);
    try {
      const notification = new Notification(content.title, {
        body: content.body,
        icon: '/favicon.svg',
        tag: content.tag,
        requireInteraction: false,
      });
      if (content.url) {
        notification.onclick = () => {
          // Bring the dashboard tab to focus and navigate to the relevant page.
          try {
            window.focus();
          } catch {
            // No-op: focus() can throw on some browsers when called from a
            // non-user-gesture context. The navigation still proceeds.
          }
          // The URL came from `renderNotification` which only ever emits
          // one of our known SPA routes — cast to satisfy SvelteKit's
          // strict route-literal type without re-listing every variant.
          // eslint-disable-next-line svelte/no-navigation-without-resolve, @typescript-eslint/no-explicit-any
          void goto(content.url as any);
          notification.close();
        };
      }
    } catch {
      // The Notification constructor can throw on some browsers when the
      // tab has been backgrounded for too long — silent fail is correct.
    }
  }

  onMount(() => {
    if (!live) return;
    return live.on(handle);
  });
</script>
