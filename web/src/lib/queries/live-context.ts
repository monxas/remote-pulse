import { getContext } from 'svelte';
import type { LiveStream } from './sse.svelte';

export function getLiveStream(): LiveStream | null {
  return (getContext('rp:live') as LiveStream | undefined) ?? null;
}
