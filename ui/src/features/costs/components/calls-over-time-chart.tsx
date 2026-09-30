"use client";

import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";

import {
  type ChartConfig,
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart";
import { formatBucket, formatBucketLong } from "@/features/platform-stats/format";
import { evenlySpacedTicks } from "@/features/platform-stats/ticks";

import type { CostSeriesPoint, Granularity } from "../schemas";
import { EmptyChart } from "./spend-over-time-chart";

interface CallsOverTimeChartProps {
  series: CostSeriesPoint[];
  granularity: Granularity;
}

const CHART_CONFIG = {
  calls: { label: "Calls", color: "var(--ink-3)" },
} satisfies ChartConfig;

/** Model calls per bucket.
 *
 *  Its own chart rather than a second axis on the spend one: calls and dollars
 *  are different scales, and a spend line that climbs while this one is flat
 *  says each call got dearer rather than that there were more of them. */
export function CallsOverTimeChart({
  series,
  granularity,
}: CallsOverTimeChartProps) {
  if (series.every((point) => point.calls === 0)) {
    return <EmptyChart>No calls in this period.</EmptyChart>;
  }

  const ticks = evenlySpacedTicks(series.map((d) => d.bucket));

  return (
    <ChartContainer config={CHART_CONFIG} className="h-[220px] w-full">
      <BarChart data={series} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="bucket"
          tickFormatter={(v: string) => formatBucket(v, granularity)}
          tickLine={false}
          axisLine={false}
          ticks={ticks}
          interval={0}
          tick={{ fontSize: 11 }}
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
              labelFormatter={(value) =>
                formatBucketLong(String(value), granularity)
              }
            />
          }
        />
        <Bar
          dataKey="calls"
          fill="var(--color-calls)"
          isAnimationActive={false}
          maxBarSize={24}
        />
      </BarChart>
    </ChartContainer>
  );
}
