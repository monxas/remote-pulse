<script lang="ts">
  import uPlot, { type Options as UPlotOptions, type AlignedData } from 'uplot';
  import 'uplot/dist/uPlot.min.css';
  import type { TimeseriesPayload } from '$lib/api';

  type SeriesSpec = {
    key: keyof TimeseriesPayload;
    label: string;
    color: string;
    unit?: string;
  };

  type Props = {
    data: TimeseriesPayload | undefined;
    series: SeriesSpec[];
    height?: number;
    title?: string;
    yMin?: number;
    yMax?: number;
  };
  const { data, series, height = 220, title, yMin, yMax }: Props = $props();

  let container = $state<HTMLDivElement | null>(null);
  let width = $state(640);
  let chart: uPlot | null = null;
  let resizeObserver: ResizeObserver | null = null;

  function resolve(c: string): string {
    if (!c.startsWith('var(')) return c;
    const match = c.match(/var\((--[^),]+)/);
    if (!match) return c;
    const cssVar = match[1];
    if (!cssVar || typeof document === 'undefined') return c;
    const v = getComputedStyle(document.documentElement).getPropertyValue(cssVar).trim();
    return v || c;
  }

  function build(): void {
    if (!container) return;
    chart?.destroy();
    chart = null;

    const ts = data?.ts ?? [];
    const aligned: AlignedData = [
      ts,
      ...series.map((s) => {
        const arr = (data?.[s.key] as (number | null)[] | undefined) ?? [];
        // Pad to ts.length so uPlot aligns rows.
        const padded = arr.length === ts.length ? arr : ts.map((_, i) => arr[i] ?? null);
        return padded;
      }),
    ];

    const axisColor = resolve('var(--text-muted)');
    const gridColor = resolve('var(--border-subtle)');

    const opts: UPlotOptions = {
      width,
      height,
      pxAlign: false,
      cursor: { show: true, drag: { x: true, y: false, setScale: false } },
      legend: { show: true, live: true },
      scales: {
        x: { time: true },
        y: {
          range: (_u, dataMin, dataMax) => {
            const lo = yMin ?? Math.min(0, dataMin ?? 0);
            const hi = yMax ?? Math.max(dataMax ?? 1, 1);
            return [lo, hi];
          },
        },
      },
      axes: [
        {
          stroke: axisColor,
          grid: { stroke: gridColor, width: 1 },
          ticks: { stroke: gridColor },
        },
        {
          stroke: axisColor,
          grid: { stroke: gridColor, width: 1 },
          ticks: { stroke: gridColor },
        },
      ],
      series: [
        { label: 'time' },
        ...series.map((s) => ({
          label: s.label,
          stroke: resolve(s.color),
          width: 1.5,
          spanGaps: false,
          points: { show: false },
          value: (_u: uPlot, raw: number | null) =>
            raw === null || raw === undefined ? '—' : `${raw.toFixed(1)}${s.unit ?? ''}`,
        })),
      ],
    };

    chart = new uPlot(opts, aligned, container);
  }

  $effect(() => {
    void data;
    void series;
    void width;
    void height;
    if (!container) return;
    build();
  });

  $effect(() => {
    if (!container) return;
    resizeObserver = new ResizeObserver((entries) => {
      const cr = entries[0]?.contentRect;
      if (cr) width = Math.max(120, Math.floor(cr.width));
    });
    resizeObserver.observe(container);
    return () => {
      resizeObserver?.disconnect();
      resizeObserver = null;
      chart?.destroy();
      chart = null;
    };
  });
</script>

<div class="w-full">
  {#if title}
    <h3 class="mb-2 text-sm font-medium text-muted">{title}</h3>
  {/if}
  <div
    bind:this={container}
    class="w-full overflow-hidden rounded-md border border-border-subtle bg-subtle/40 p-2"
    style:height="{height + 30}px"
    role="img"
    aria-label={title ?? 'time series chart'}
  ></div>
</div>
