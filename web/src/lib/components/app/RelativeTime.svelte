<script lang="ts">
  import { formatRelative, secondsAgoFromIso } from '$lib/utils/relative-time';

  type Props = {
    iso?: string | null;
    secondsAgo?: number | null;
    class?: string;
  };
  const { iso, secondsAgo, class: className }: Props = $props();

  let now = $state(Date.now());

  $effect(() => {
    const id = setInterval(() => {
      now = Date.now();
    }, 1000);
    return () => clearInterval(id);
  });

  const computed = $derived.by(() => {
    if (iso) return secondsAgoFromIso(iso, now);
    if (secondsAgo === null || secondsAgo === undefined) return null;
    // Treat `secondsAgo` as a baseline captured at the last refetch; advance
    // it locally by `(now - mountedAt)`. We approximate by using the value
    // directly — refetch happens every 5s anyway.
    return secondsAgo;
  });

  const label = $derived(formatRelative(computed));
</script>

<time class={className} datetime={iso ?? undefined} aria-label={iso ?? label} title={iso ?? label}>
  {label}
</time>
