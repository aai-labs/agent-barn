"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

import type { CostSeriesPoint } from "../schemas";

interface CostsChartProps {
  timeSeries: CostSeriesPoint[];
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr + "T00:00:00");
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function formatDollar(value: number): string {
  return `$${value.toFixed(4)}`;
}

interface TooltipPayload {
  value: number;
  dataKey: string;
}

interface CustomTooltipProps {
  active?: boolean;
  payload?: TooltipPayload[];
  label?: string;
}

function CustomTooltip({ active, payload, label }: CustomTooltipProps) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-white border border-gray-200 rounded-xl shadow-lg px-4 py-3 text-sm">
      <div className="text-gray-500 font-medium mb-1">
        {label ? formatDate(label) : ""}
      </div>
      <div className="text-gray-900 font-semibold text-[15px]">
        {formatDollar(payload[0]?.value ?? 0)}
      </div>
    </div>
  );
}

export function CostsChart({ timeSeries }: CostsChartProps) {
  if (timeSeries.length === 0) {
    return (
      <div className="flex items-center justify-center h-[200px] text-[14px] text-gray-400">
        No cost data for this period.
      </div>
    );
  }

  // Calculate up to 8 evenly spaced ticks for the X-axis
  const TARGET_TICKS = 8;
  const rawTicks: string[] = [];
  if (timeSeries.length <= TARGET_TICKS) {
    rawTicks.push(...timeSeries.map((d) => d.date));
  } else {
    const step = (timeSeries.length - 1) / (TARGET_TICKS - 1);
    for (let i = 0; i < TARGET_TICKS; i++) {
      const index = Math.min(Math.round(i * step), timeSeries.length - 1);
      rawTicks.push(timeSeries[index].date);
    }
  }
  const uniqueTicks = Array.from(new Set(rawTicks));

  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart
        data={timeSeries}
        margin={{ top: 8, right: 16, left: 0, bottom: 0 }}
      >
        <CartesianGrid
          strokeDasharray="3 3"
          stroke="#f1f5f9"
          vertical={false}
        />
        <XAxis
          dataKey="date"
          tickFormatter={formatDate}
          tick={{ fontSize: 12, fill: "#94a3b8" }}
          axisLine={false}
          tickLine={false}
          ticks={uniqueTicks}
          interval={0}
        />
        <YAxis
          tickFormatter={(v: number) => `$${v.toFixed(3)}`}
          tick={{ fontSize: 11, fill: "#94a3b8" }}
          axisLine={false}
          tickLine={false}
          width={60}
        />
        <Tooltip content={<CustomTooltip />} cursor={{ fill: "#f8fafc" }} />
        <Bar
          dataKey="cost"
          fill="#6366f1"
          radius={[4, 4, 0, 0]}
          maxBarSize={40}
        />
      </BarChart>
    </ResponsiveContainer>
  );
}
