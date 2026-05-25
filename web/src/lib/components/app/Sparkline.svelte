<script lang="ts">
  import uPlot, { type Options as UPlotOptions, type AlignedData } from 'uplot';
  import 'uplot/dist/uPlot.min.css';

  type Props = {
    data: { ts: number[]; values: (number | null)[] };
    width?: number;
    height?: number;
    color?: string;
    label?: string;
    yMin?: number;
    yMax?: number;
    /** Plain text title shown in the hover tooltip ("CPU", "Memory"). */
    title?: string;
    /** Unit suffix shown next to the hover value ("%", "ms", ""). */
    unit?: string;
  };
  const {
    data,
    width = 120,
    height = 32,
    color = 'var(--accent-solid)',
    label,
    yMin,
    yMax,
    title,
    unit = '%',
  }: Props = $props();

  let container = $state<HTMLDivElement | null>(null);
  let chart: uPlot | null = null;
  let tooltipValue = $state<string | null>(null);

  function resolveColor(c: string): string {
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

    const stroke = resolveColor(color);

    const aligned: AlignedData = [data.ts, data.values.map((v) => (v === null ? null : v))];

    const opts: UPlotOptions = {
      width,
      height,
      pxAlign: false,
      cursor: {
        show: true,
        x: false,
        y: false,
        points: { show: false },
        drag: { x: false, y: false, setScale: false },
      },
      legend: { show: false },
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
      axes: [{ show: false }, { show: false }],
      series: [
        {},
        {
          label: label ?? 'value',
          stroke,
          width: 1.5,
          spanGaps: false,
          points: { show: false },
        },
      ],
      hooks: {
        setCursor: [
          (u) => {
            const idx = u.cursor.idx;
            if (idx === null || idx === undefined) {
              tooltipValue = null;
              return;
            }
            const v = u.data[1]?.[idx];
            tooltipValue = v === null || v === undefined ? null : v.toFixed(1);
          },
        ],
      },
    };

    chart = new uPlot(opts, aligned, container);
  }

  $effect(() => {
    void data;
    void width;
    void height;
    void color;
    if (!container) return;
    build();
    return () => {
      chart?.destroy();
      chart = null;
    };
  });
</script>

<div
  class="relative inline-block"
  style:width="{width}px"
  style:height="{height}px"
  role="img"
  aria-label={title ? `${title} sparkline` : 'sparkline'}
>
  <div bind:this={container} class="absolute inset-0"></div>
  {#if tooltipValue !== null}
    <span
      class="pointer-events-none absolute -top-5 right-0 rounded-sm bg-elevated px-1.5 py-0.5 font-mono text-[10px] text-default shadow-sm"
    >
      {tooltipValue}{unit}
    </span>
  {/if}
</div>
