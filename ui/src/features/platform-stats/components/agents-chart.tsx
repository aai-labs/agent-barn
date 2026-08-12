"use client";

import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  XAxis,
  YAxis,
} from "recharts";

import {
  type ChartConfig,
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart";

import { formatBucket, formatBucketLong } from "../format";
import type { Granularity, PlatformAgentSeriesPoint } from "../schemas";
import { evenlySpacedTicks } from "../ticks";

interface AgentsChartProps {
  series: PlatformAgentSeriesPoint[];
  granularity: Granularity;
}

const CHART_CONFIG = {
  existing: { label: "Agents", color: "var(--ink-4)" },
  active: { label: "Active", color: "var(--ink)" },
} satisfies ChartConfig;

export function AgentsChart({ series, granularity }: AgentsChartProps) {
  if (series.length === 0) {
    return (
      <div className="flex h-[200px] items-center justify-center text-[14px] text-muted-foreground">
        No agents in this period.
      </div>
    );
  }

  const ticks = evenlySpacedTicks(series.map((d) => d.bucket));

  return (
    <ChartContainer config={CHART_CONFIG} className="h-[200px] w-full">
      <ComposedChart
        data={series}
        margin={{ top: 8, right: 16, left: 0, bottom: 0 }}
      >
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
              // `created` is carried in the data but drawn as no series, so the
              // default tooltip would never surface it. Append it to the last
              // row, and only when something was actually created.
              formatter={(value, name, item, index) => {
                const created = (item?.payload as PlatformAgentSeriesPoint | undefined)?.created ?? 0;
                const label = CHART_CONFIG[name as keyof typeof CHART_CONFIG]?.label ?? name;
                return (
                  <>
                    <span className="text-muted-foreground">{label}</span>
                    <span className="ml-auto font-mono font-medium tabular-nums text-foreground">
                      {Number(value).toLocaleString()}
                    </span>
                    {index === 1 && created > 0 && (
                      <div className="text-muted-foreground basis-full">
                        +{created.toLocaleString()} created
                      </div>
                    )}
                  </>
                );
              }}
            />
          }
        />
        <ChartLegend content={<ChartLegendContent />} verticalAlign="top" />
        <Area
          type="stepAfter"
          dataKey="existing"
          stroke="var(--color-existing)"
          fill="var(--color-existing)"
          fillOpacity={0.15}
          strokeWidth={1.5}
          isAnimationActive={false}
        />
        {/* Linear, not monotone: a smoothed curve would draw values between
            buckets that the counts never claim. */}
        <Line
          type="linear"
          dataKey="active"
          stroke="var(--color-active)"
          strokeWidth={2}
          dot={false}
          isAnimationActive={false}
        />
      </ComposedChart>
    </ChartContainer>
  );
}
