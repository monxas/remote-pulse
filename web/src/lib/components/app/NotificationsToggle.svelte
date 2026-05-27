<script lang="ts">
  /**
   * Browser-notification opt-in panel rendered inside Settings → Notifications.
   *
   * Three permission states, each with a distinct CTA:
   *  - `default` (never asked)    → "Enable notifications" button.
   *  - `granted`                  → status + per-event-type opt-in checkboxes + Test button.
   *  - `denied`                   → instructions to unblock via the browser settings UI.
   *
   * Browsers don't expose a programmatic way to *revoke* notification
   * permission — only the user can do that from their browser's site
   * settings. We surface that fact explicitly rather than show a dead
   * "Disable" button.
   *
   * Opt-in checkboxes are persisted under `rp:notifications:${userEmail}`
   * via `notifications-state.ts` so the dispatcher and Settings UI agree.
   */
  import { onMount } from 'svelte';
  import { Bell, BellOff, Check, ShieldAlert } from '@lucide/svelte';
  import { toast } from 'svelte-sonner';
  import { Button } from '$lib/components/ui/button';
  import { Badge } from '$lib/components/ui/badge';
  import { userStore } from '$lib/stores/user.svelte';
  import {
    ADMIN_ONLY_EVENT_TYPES,
    ALL_NOTIFICATION_EVENT_TYPES,
    DEFAULT_OPT_INS,
    EVENT_TYPE_LABELS,
    loadOptIns,
    saveOptIns,
    type NotificationEventType,
    type NotificationOptIns,
  } from './notifications-state';

  type SupportedPermission = 'default' | 'granted' | 'denied' | 'unsupported';

  let permission = $state<SupportedPermission>('default');
  let optIns = $state<NotificationOptIns>({ ...DEFAULT_OPT_INS });

  const userEmail = $derived(userStore.value?.user_email ?? null);
  const userRole = $derived(userStore.value?.user_role ?? null);
  const isAdmin = $derived(userRole === 'admin');

  // Hydrate from window/localStorage on mount only — both APIs are SSR-unsafe.
  onMount(() => {
    if (typeof window === 'undefined') return;
    if (!('Notification' in window)) {
      permission = 'unsupported';
      return;
    }
    permission = Notification.permission;
    try {
      optIns = loadOptIns(window.localStorage, userEmail);
    } catch {
      optIns = { ...DEFAULT_OPT_INS };
    }
  });

  async function requestPermission(): Promise<void> {
    if (permission === 'unsupported') return;
    try {
      const result = await Notification.requestPermission();
      permission = result;
      if (result === 'granted') {
        toast.success('Notifications enabled');
      } else if (result === 'denied') {
        toast.error('Notifications blocked by browser');
      }
    } catch (err) {
      toast.error(`Could not request permission: ${(err as Error).message}`);
    }
  }

  function toggleOptIn(type: NotificationEventType): void {
    const next: NotificationOptIns = { ...optIns, [type]: !optIns[type] };
    optIns = next;
    if (typeof window !== 'undefined') {
      try {
        saveOptIns(window.localStorage, userEmail, next);
      } catch {
        // localStorage may be unavailable (private mode quota, etc.) —
        // swallow because the in-memory state still reflects the toggle.
      }
    }
  }

  function fireTestNotification(): void {
    if (permission !== 'granted') return;
    try {
      new Notification('Remote-Pulse test', {
        body: 'Notifications are working. You can close this.',
        icon: '/favicon.svg',
        tag: 'rp-test-notification',
      });
    } catch (err) {
      toast.error(`Could not fire notification: ${(err as Error).message}`);
    }
  }

  // Rows visible to the current user — non-admins don't even see the
  // admin-only audit toggles so they can't enable categories the
  // dispatcher would silently drop anyway.
  const visibleEventTypes = $derived(
    ALL_NOTIFICATION_EVENT_TYPES.filter((t) => !ADMIN_ONLY_EVENT_TYPES.has(t) || isAdmin),
  );
</script>

<div class="space-y-4" data-testid="notifications-toggle">
  <div
    class="flex flex-col gap-3 rounded-lg border border-border-subtle bg-subtle/40 p-4 sm:flex-row sm:items-center sm:justify-between"
  >
    <div class="flex items-start gap-3">
      {#if permission === 'granted'}
        <Bell class="mt-0.5 size-5 text-success-text" aria-hidden="true" />
      {:else if permission === 'denied' || permission === 'unsupported'}
        <BellOff class="mt-0.5 size-5 text-danger-text" aria-hidden="true" />
      {:else}
        <Bell class="mt-0.5 size-5 text-muted" aria-hidden="true" />
      {/if}
      <div>
        <h3 class="text-sm font-semibold">Browser notifications</h3>
        <p class="text-xs text-muted">
          Fire native OS notifications when high-signal events arrive and the dashboard tab is in
          the background. Works alongside (or instead of) Telegram alerts.
        </p>
      </div>
    </div>
    <div class="shrink-0">
      {#if permission === 'unsupported'}
        <Badge variant="muted">Not supported</Badge>
      {:else if permission === 'default'}
        <Button size="sm" onclick={requestPermission} data-testid="enable-notifications">
          <Bell class="mr-1 size-4" aria-hidden="true" />
          Enable notifications
        </Button>
      {:else if permission === 'granted'}
        <Badge variant="default" data-testid="notifications-enabled-badge">
          <Check class="mr-1 size-3.5" aria-hidden="true" />
          Enabled
        </Badge>
      {:else}
        <Badge variant="muted" data-testid="notifications-denied-badge">
          <ShieldAlert class="mr-1 size-3.5" aria-hidden="true" />
          Blocked
        </Badge>
      {/if}
    </div>
  </div>

  {#if permission === 'denied'}
    <p
      class="rounded-md border border-border-subtle bg-subtle/40 p-3 text-xs text-muted"
      data-testid="notifications-denied-help"
    >
      Your browser is blocking notifications for this site. Open the site settings (lock icon →
      Permissions) and set <strong>Notifications</strong> to <em>Allow</em>, then reload this page.
    </p>
  {/if}

  {#if permission === 'granted'}
    <div class="space-y-3" data-testid="notifications-options">
      <div>
        <h4 class="text-sm font-semibold">Notify me about</h4>
        <p class="text-xs text-muted">
          Tab must be unfocused — when you're already looking at the dashboard, in-app toasts handle
          it.
        </p>
      </div>
      <ul class="space-y-2">
        {#each visibleEventTypes as type (type)}
          <li>
            <label class="flex cursor-pointer items-center gap-2 text-sm">
              <input
                type="checkbox"
                class="size-4 cursor-pointer accent-[var(--accent-solid)]"
                checked={optIns[type]}
                onchange={() => toggleOptIn(type)}
                data-testid={`opt-in-${type}`}
              />
              <span>{EVENT_TYPE_LABELS[type]}</span>
              {#if ADMIN_ONLY_EVENT_TYPES.has(type)}
                <Badge variant="muted" class="ml-1">admin</Badge>
              {/if}
            </label>
          </li>
        {/each}
      </ul>

      <div
        class="flex flex-col gap-2 border-t border-border-subtle pt-3 sm:flex-row sm:items-center sm:justify-between"
      >
        <p class="text-xs text-muted">
          To turn notifications off entirely, revoke the permission in your browser's site settings.
        </p>
        <Button
          size="sm"
          variant="ghost"
          onclick={fireTestNotification}
          data-testid="test-notification-btn"
        >
          Send test notification
        </Button>
      </div>
    </div>
  {/if}
</div>
