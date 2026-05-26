import type { Page, Route } from '@playwright/test';

/**
 * Helpers for driving the SSE stream from Playwright tests.
 *
 * Playwright's `route.fulfill` doesn't support streaming bodies, so we
 * use `page.evaluate` to register a tiny mock `EventSource` constructor
 * that exposes a global hook for the test to push events. The SPA's
 * SSE bridge is the only consumer of `EventSource` so this is a safe
 * targeted shim.
 *
 * Usage::
 *
 *   await installFakeEventSource(page);
 *   await mockSseHead(page);
 *   await page.goto('/');
 *   await pushSseEvent(page, 'command.status_change', {
 *     command_id: 'cmd-1', host_id: 'host-1', status: 'failed',
 *   });
 */

/**
 * Inject a fake `EventSource` into the page before any script runs.
 * Events are pushed via `window.__pushSse(name, data)`.
 */
export async function installFakeEventSource(page: Page): Promise<void> {
  await page.addInitScript(() => {
    type Listener = (e: MessageEvent) => void;
    class FakeES extends EventTarget {
      static CONNECTING = 0;
      static OPEN = 1;
      static CLOSED = 2;
      CONNECTING = 0;
      OPEN = 1;
      CLOSED = 2;
      readyState = 0;
      url: string;
      withCredentials: boolean;
      onopen: ((e: Event) => void) | null = null;
      onerror: ((e: Event) => void) | null = null;
      onmessage: ((e: MessageEvent) => void) | null = null;
      private namedListeners = new Map<string, Set<Listener>>();
      constructor(url: string, init?: { withCredentials?: boolean }) {
        super();
        this.url = url;
        this.withCredentials = Boolean(init?.withCredentials);
        // Track this instance globally so the test can push events.
        const g = window as unknown as Window & {
          __sseInstances?: FakeES[];
          __pushSse?: (name: string, data: unknown, id?: string) => void;
        };
        g.__sseInstances = g.__sseInstances || [];
        g.__sseInstances.push(this);
        // Open asynchronously to mimic real EventSource.
        setTimeout(() => {
          this.readyState = 1;
          const ev = new Event('open');
          this.dispatchEvent(ev);
          this.onopen?.(ev);
        }, 0);
        g.__pushSse = (name: string, data: unknown, id?: string) => {
          for (const es of g.__sseInstances ?? []) {
            const dataStr = typeof data === 'string' ? data : JSON.stringify(data);
            const evt = new MessageEvent(name, { data: dataStr, lastEventId: id ?? '' });
            es.dispatchEvent(evt);
            if (name === 'message') es.onmessage?.(evt);
          }
        };
      }
      override addEventListener(type: string, cb: EventListenerOrEventListenerObject | null): void {
        if (!cb) return;
        super.addEventListener(type, cb as EventListener);
        if (typeof cb === 'function') {
          let bucket = this.namedListeners.get(type);
          if (!bucket) {
            bucket = new Set();
            this.namedListeners.set(type, bucket);
          }
          bucket.add(cb as Listener);
        }
      }
      close(): void {
        this.readyState = 2;
      }
    }
    (window as unknown as { EventSource: typeof FakeES }).EventSource = FakeES;
  });
}

/** Make the HEAD probe succeed without burning a real network request. */
export async function mockSseHead(page: Page): Promise<void> {
  await page.route('**/v1/dash/stream', (route: Route) => {
    if (route.request().method() === 'HEAD') {
      return route.fulfill({ status: 200, body: '' });
    }
    // Real GET shouldn't fire (FakeES intercepts) but if it does just
    // return an empty stream so the bridge doesn't crash.
    return route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: '',
    });
  });
}

/** Push a named SSE event into every active FakeEventSource on the page. */
export async function pushSseEvent(
  page: Page,
  name: string,
  data: unknown,
  id?: string,
): Promise<void> {
  await page.evaluate(
    ({ name, data, id }) => {
      const g = window as unknown as {
        __pushSse?: (n: string, d: unknown, i?: string) => void;
      };
      g.__pushSse?.(name, data, id);
    },
    { name, data, id },
  );
}
