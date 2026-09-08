"use client";

import { CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";

import {
  type ChartConfig,
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart";
import { formatBucket, formatBucketLong } from "@/features/platform-stats/format";
import { evenlySpacedTicks } from "@/features/platform-stats/ticks";

import { formatTokens } from "../format";
import type { Granularity, TokenSeriesPoint } from "../schemas";
import { EmptyChart } from "./spend-over-time-chart";

interface PromptTokensChartProps {
  series: TokenSeriesPoint[];
  granularity: Granularity;
}

const CHART_CONFIG = {
  avgPromptTokens: { label: "Avg prompt tokens", color: "var(--ink-3)" },
} satisfies ChartConfig;

/** Average prompt size over time.
 *
 *  Worth its own chart next to spend: prompt tokens are the input side of the
 *  bill, so a cost line that climbs while this one is flat means prices or
 *  volume moved, and one that climbs with it means the prompts got bigger. */
export function PromptTokensChart({
  series,
  granularity,
}: PromptTokensChartProps) {
  if (series.length === 0) {
    return <EmptyChart>No calls in this period.</EmptyChart>;
  }

  const ticks = evenlySpacedTicks(series.map((d) => d.bucket));

  return (
    <ChartContainer config={CHART_CONFIG} className="h-[220px] w-full">
      <LineChart data={series} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
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
          width={56}
          tickFormatter={(v: number) => formatTokens(v)}
          tick={{ fontSize: 11 }}
        />
        <ChartTooltip
          content={
            <ChartTooltipContent
              labelFormatter={(value) =>
                formatBucketLong(String(value), granularity)
              }
              formatter={(value) => formatTokens(Number(value))}
            />
          }
        />
        <Line
          dataKey="avgPromptTokens"
          type="monotone"
          stroke="var(--color-avgPromptTokens)"
          strokeWidth={2}
          dot={false}
          isAnimationActive={false}
        />
      </LineChart>
    </ChartContainer>
  );
}
