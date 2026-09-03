"use client";

import { useMemo } from "react";
import { CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";

import {
  type ChartConfig,
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart";
import { formatBucket, formatBucketLong } from "@/features/platform-stats/format";
import { evenlySpacedTicks } from "@/features/platform-stats/ticks";

import { formatSpendCompact } from "../format";
import type { AgentSpendSeriesPoint, Granularity } from "../schemas";
import { EmptyChart } from "./spend-over-time-chart";

interface SpendByAgentChartProps {
  series: AgentSpendSeriesPoint[];
  granularity: Granularity;
}

// One colour per line, cycled. The server already caps the number of agents it
// returns, so this list only has to be as long as that cap.
const LINE_COLORS = [
  "var(--ink-2)",
  "var(--ink-3)",
  "var(--ink-4)",
  "var(--ink-5)",
  "var(--acc)",
  "var(--ok)",
  "var(--warn)",
  "var(--err)",
];

/** Per-agent spend over time.
 *
 *  The server sends long-form points (one per bucket per agent) and omits the
 *  zeros. Recharts wants one row per bucket with a column per line, so the
 *  pivot happens here — and every missing point becomes an explicit 0 rather
 *  than a gap, so a line drops to the floor instead of jumping the quiet spell. */
export function SpendByAgentChart({ series, granularity }: SpendByAgentChartProps) {
  const { data, config, agentKeys, buckets } = useMemo(() => {
    const agentNames = new Map<string, string>();
    for (const point of series) {
      const key = point.agentId ?? "unattributed";
      if (!agentNames.has(key)) {
        agentNames.set(key, point.agentName ?? "Unattributed");
      }
    }

    const bucketList = [...new Set(series.map((p) => p.bucket))].sort();
    const rows = bucketList.map((bucket) => {
      const row: Record<string, string | number> = { bucket };
      for (const key of agentNames.keys()) row[key] = 0;
      return row;
    });
    const rowByBucket = new Map(rows.map((row) => [row.bucket as string, row]));
    for (const point of series) {
      const row = rowByBucket.get(point.bucket);
      if (row) row[point.agentId ?? "unattributed"] = point.spend;
    }

    const chartConfig: ChartConfig = {};
    [...agentNames.entries()].forEach(([key, name], index) => {
      chartConfig[key] = {
        label: name,
        color: LINE_COLORS[index % LINE_COLORS.length],
      };
    });

    return {
      data: rows,
      config: chartConfig,
      agentKeys: [...agentNames.keys()],
      buckets: bucketList,
    };
  }, [series]);

  if (series.length === 0) {
    return <EmptyChart>No agent spend in this period.</EmptyChart>;
  }

  const ticks = evenlySpacedTicks(buckets);

  return (
    <ChartContainer config={config} className="h-[260px] w-full">
      <LineChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
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
              // ChartTooltipContent hands the whole row to `formatter`, indicator and
              // name included — returning only the value would leave a column of
              // bare dollar amounts with no way to tell which agent each belongs to.
              // So the row is rebuilt here: swatch, agent name, then the amount.
              formatter={(value, name, item) => (
                <>
                  <div
                    className="h-2.5 w-2.5 shrink-0 rounded-[2px]"
                    style={{ backgroundColor: item?.color }}
                  />
                  <div className="flex flex-1 items-center justify-between gap-3 leading-none">
                    <span className="text-muted-foreground">
                      {config[String(name)]?.label ?? String(name)}
                    </span>
                    <span className="font-mono font-medium text-foreground tabular-nums">
                      {formatSpendCompact(Number(value))}
                    </span>
                  </div>
                </>
              )}
            />
          }
        />
        <ChartLegend content={<ChartLegendContent />} verticalAlign="top" />
        {agentKeys.map((key) => (
          <Line
            key={key}
            dataKey={key}
            type="monotone"
            stroke={`var(--color-${key})`}
            strokeWidth={1.75}
            dot={false}
            isAnimationActive={false}
          />
        ))}
      </LineChart>
    </ChartContainer>
  );
}
