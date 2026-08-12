"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { formatBucket, formatBucketLong } from "../format";
import type { Granularity, PlatformMessageSeriesPoint } from "../schemas";
import { evenlySpacedTicks } from "../ticks";

interface MessagesChartProps {
  series: PlatformMessageSeriesPoint[];
  granularity: Granularity;
}


interface TooltipPayload {
  value: number;
  dataKey: string;
  name: string;
}

interface CustomTooltipProps {
  active?: boolean;
  payload?: TooltipPayload[];
  label?: string;
  granularity: Granularity;
}

function CustomTooltip({ active, payload, label, granularity }: CustomTooltipProps) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-white border border-gray-200 rounded-xl shadow-lg px-4 py-3 text-sm">
      <div className="text-gray-500 font-medium mb-1">
        {label ? formatBucketLong(label, granularity) : ""}
      </div>
      {payload.map((entry) => (
        <div
          key={entry.dataKey}
          className="text-gray-900 font-semibold text-[15px]"
        >
          {entry.name}: {entry.value.toLocaleString()}
        </div>
      ))}
    </div>
  );
}

export function MessagesChart({ series, granularity }: MessagesChartProps) {
  if (series.length === 0) {
    return (
      <div className="flex items-center justify-center h-[200px] text-[14px] text-gray-400">
        No messages in this period.
      </div>
    );
  }

  const ticks = evenlySpacedTicks(series.map((d) => d.bucket));

  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart
        data={series}
        margin={{ top: 8, right: 16, left: 0, bottom: 0 }}
      >
        <CartesianGrid
          strokeDasharray="3 3"
          stroke="#f1f5f9"
          vertical={false}
        />
        <XAxis
          dataKey="bucket"
          tickFormatter={(v: string) => formatBucket(v, granularity)}
          tick={{ fontSize: 11, fill: "var(--ink-4)" }}
          axisLine={false}
          tickLine={false}
          ticks={ticks}
          interval={0}
        />
        <YAxis
          tick={{ fontSize: 11, fill: "var(--ink-4)" }}
          axisLine={false}
          tickLine={false}
          width={48}
          allowDecimals={false}
        />
        <Tooltip content={<CustomTooltip granularity={granularity} />} cursor={{ fill: "#f8fafc" }} />
        <Legend
          verticalAlign="top"
          align="right"
          height={28}
          iconType="circle"
          iconSize={8}
          wrapperStyle={{ fontSize: 12, color: "var(--ink-3)" }}
        />
        <Bar
          isAnimationActive={false}
          dataKey="inbound"
          name="Received"
          stackId="messages"
          fill="var(--ink-3)"
          maxBarSize={40}
        />
        <Bar
          isAnimationActive={false}
          dataKey="outbound"
          name="Sent"
          stackId="messages"
          fill="var(--ink-5, #cbd5e1)"
          radius={[4, 4, 0, 0]}
          maxBarSize={40}
        />
      </BarChart>
    </ResponsiveContainer>
  );
}
