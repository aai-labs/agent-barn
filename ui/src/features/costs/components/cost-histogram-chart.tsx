"use client";

import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";

import {
  type ChartConfig,
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart";

import { formatHistogramBand, formatHistogramTick } from "../format";
import type { CostHistogramBucket } from "../schemas";
import { EmptyChart } from "./spend-over-time-chart";

interface CostHistogramChartProps {
  buckets: CostHistogramBucket[];
}

const CHART_CONFIG = {
  calls: { label: "Calls", color: "var(--ink-3)" },
} satisfies ChartConfig;

/** Distribution of per-call cost over fixed dollar bands.
 *
 *  Fixed bands rather than bands derived from the data, so the shape is
 *  comparable between two filters and between two organizations.
 *
 *  The cheapest band also holds calls whose cost has not been recovered yet —
 *  they record $0 until the healing job reaches them, so they read as nearly
 *  free when their real cost is simply not known. The band is labelled to say so. */
export function CostHistogramChart({ buckets }: CostHistogramChartProps) {
  const total = buckets.reduce((sum, b) => sum + b.calls, 0);
  if (total === 0) {
    return <EmptyChart>No calls in this period.</EmptyChart>;
  }

  // `band` is the full range and stays the category key, so the tooltip can name
  // the exact span. `tick` is the terse version the axis draws.
  const data = buckets.map((bucket) => ({
    band: formatHistogramBand(bucket.lower, bucket.upper),
    tick: formatHistogramTick(bucket.lower, bucket.upper),
    calls: bucket.calls,
  }));

  return (
    <ChartContainer config={CHART_CONFIG} className="h-[220px] w-full">
      <BarChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" vertical={false} />
        {/* Ticks are drawn from `tick`, not the category key, so the axis can be
            terse while the tooltip stays exact. Indexing by position rather than
            by label keeps the two in step even if two bands ever render alike. */}
        <XAxis
          dataKey="band"
          tickFormatter={(_value, index) => data[index]?.tick ?? ""}
          tickLine={false}
          axisLine={false}
          interval={0}
          tick={{ fontSize: 10 }}
        />
        <YAxis
          tickLine={false}
          axisLine={false}
          width={48}
          allowDecimals={false}
          tick={{ fontSize: 11 }}
        />
        <ChartTooltip
          content={
            <ChartTooltipContent
              labelFormatter={(value) => `Calls costing ${String(value)}`}
            />
          }
        />
        <Bar
          dataKey="calls"
          fill="var(--color-calls)"
          isAnimationActive={false}
          maxBarSize={48}
        />
      </BarChart>
    </ChartContainer>
  );
}
