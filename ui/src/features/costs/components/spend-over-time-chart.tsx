"use client";

import { Area, AreaChart, CartesianGrid, XAxis, YAxis } from "recharts";

import {
  type ChartConfig,
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart";
import { formatBucket, formatBucketLong } from "@/features/platform-stats/format";
import { evenlySpacedTicks } from "@/features/platform-stats/ticks";

import { formatSpendCompact } from "../format";
import type { CostSeriesPoint, Granularity } from "../schemas";

interface SpendOverTimeChartProps {
  series: CostSeriesPoint[];
  granularity: Granularity;
}

// Declared once so the tooltip and the mark cannot disagree about either.
const CHART_CONFIG = {
  spend: { label: "Spend", color: "var(--ink-3)" },
} satisfies ChartConfig;

export function SpendOverTimeChart({
  series,
  granularity,
}: SpendOverTimeChartProps) {
  if (series.length === 0) {
    return <EmptyChart>No spend in this period.</EmptyChart>;
  }

  const ticks = evenlySpacedTicks(series.map((d) => d.bucket));

  return (
    <ChartContainer config={CHART_CONFIG} className="h-[220px] w-full">
      <AreaChart data={series} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
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
          width={64}
          tickFormatter={formatSpendCompact}
          tick={{ fontSize: 11 }}
        />
        <ChartTooltip
          content={
            <ChartTooltipContent
              labelFormatter={(value) =>
                formatBucketLong(String(value), granularity)
              }
              formatter={(value) => formatSpendCompact(Number(value))}
            />
          }
        />
        <Area
          dataKey="spend"
          type="monotone"
          stroke="var(--color-spend)"
          fill="var(--color-spend)"
          fillOpacity={0.15}
          strokeWidth={2}
          isAnimationActive={false}
        />
      </AreaChart>
    </ChartContainer>
  );
}

export function EmptyChart({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-[220px] items-center justify-center text-[14px] text-muted-foreground">
      {children}
    </div>
  );
}
