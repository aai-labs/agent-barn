"use client";

import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { formatBucket, formatBucketLong } from "../format";
import type { Granularity, PlatformAgentSeriesPoint } from "../schemas";
import { evenlySpacedTicks } from "../ticks";

interface AgentsChartProps {
  series: PlatformAgentSeriesPoint[];
  granularity: Granularity;
}


interface TooltipPayload {
  value: number;
  payload: PlatformAgentSeriesPoint;
}

interface CustomTooltipProps {
  active?: boolean;
  payload?: TooltipPayload[];
  label?: string;
  granularity: Granularity;
}

function CustomTooltip({ active, payload, label, granularity }: CustomTooltipProps) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload;
  return (
    <div className="bg-white border border-gray-200 rounded-xl shadow-lg px-4 py-3 text-sm">
      <div className="text-gray-500 font-medium mb-1">
        {label ? formatBucketLong(label, granularity) : ""}
      </div>
      <div className="text-gray-900 font-semibold text-[15px]">
        {point.existing.toLocaleString()} agents
      </div>
      <div className="text-gray-500">
        {point.active.toLocaleString()} active
      </div>
      {point.created > 0 && (
        <div className="text-gray-500">+{point.created} created</div>
      )}
    </div>
  );
}

export function AgentsChart({ series, granularity }: AgentsChartProps) {
  if (series.length === 0) {
    return (
      <div className="flex items-center justify-center h-[200px] text-[14px] text-gray-400">
        No agents in this period.
      </div>
    );
  }

  const ticks = evenlySpacedTicks(series.map((d) => d.bucket));

  return (
    <ResponsiveContainer width="100%" height={200}>
      <ComposedChart
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
        <Area
          isAnimationActive={false}
          type="stepAfter"
          dataKey="existing"
          name="Agents"
          stroke="var(--ink-4)"
          fill="var(--ink-4)"
          fillOpacity={0.14}
          strokeWidth={1.5}
        />
        {/* Linear, not monotone: a smoothed curve would draw values between
            days that the daily counts never claim. */}
        <Line
          isAnimationActive={false}
          type="linear"
          dataKey="active"
          name="Active"
          stroke="var(--ink)"
          strokeWidth={2}
          dot={false}
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
