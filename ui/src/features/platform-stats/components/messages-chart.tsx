"use client";

import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";

import {
  type ChartConfig,
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart";

import { formatBucket, formatBucketLong } from "../format";
import type { Granularity, PlatformMessageSeriesPoint } from "../schemas";
import { evenlySpacedTicks } from "../ticks";

interface MessagesChartProps {
  series: PlatformMessageSeriesPoint[];
  granularity: Granularity;
}

// Colours and labels are declared once here, so the legend, the tooltip and the
// marks cannot disagree about either. `var(--color-<key>)` resolves per series.
const CHART_CONFIG = {
  inbound: { label: "Received", color: "var(--ink-3)" },
  outbound: { label: "Sent", color: "var(--ink-5)" },
} satisfies ChartConfig;

export function MessagesChart({ series, granularity }: MessagesChartProps) {
  if (series.length === 0) {
    return (
      <div className="flex h-[220px] items-center justify-center text-[14px] text-muted-foreground">
        No messages in this period.
      </div>
    );
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
        <ChartLegend content={<ChartLegendContent />} verticalAlign="top" />
        <Bar
          dataKey="inbound"
          stackId="messages"
          fill="var(--color-inbound)"
          isAnimationActive={false}
          maxBarSize={40}
        />
        <Bar
          dataKey="outbound"
          stackId="messages"
          fill="var(--color-outbound)"
          radius={[4, 4, 0, 0]}
          isAnimationActive={false}
          maxBarSize={40}
        />
      </BarChart>
    </ChartContainer>
  );
}
