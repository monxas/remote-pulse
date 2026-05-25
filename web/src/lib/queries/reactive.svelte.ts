import { writable, type Readable } from 'svelte/store';

/**
 * Bridge between Svelte 5 runes and Svelte stores.
 *
 * Returns a `Readable<T>` whose value follows an `$effect`-tracked
 * accessor. Use inside `.svelte` files where the accessor reads `$state` /
 * `$derived` runes — the surrounding component must remain mounted so the
 * `$effect` keeps running.
 */
export function runeReadable<T>(accessor: () => T): Readable<T> {
  const w = writable<T>(accessor());
  $effect(() => {
    w.set(accessor());
  });
  return { subscribe: w.subscribe };
}
