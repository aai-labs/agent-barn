"use client";

import { memo, useMemo } from "react";
import { Area, AreaChart, CartesianGrid, ReferenceLine, XAxis, YAxis } from "recharts";

import {
  type ChartConfig,
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart";
import { EmptyChart } from "@/features/costs/components/spend-over-time-chart";

import {
  formatBytes,
  formatCores,
  formatShare,
  formatUsageTick,
  formatUsageTooltipTime,
} from "../format";
import type { ResourceUsagePoint, ResourceUsageRange } from "../schemas";

interface UsageAreaChartProps {
  points: { bucket: string; value: number | null }[];
  range: ResourceUsageRange;
  label: string;
  format: (value: number) => string;
  /** Drawn as a dashed line, and the top of the axis, so the gap to it is the headroom. */
  limit?: number | null;
  /** What the pod asks for, drawn as a second dashed line, in grey so it is not read as a limit. */
  request?: number | null;
  /** The axis never tops out below this, so a share of time that peaks at 2% is not
   *  stretched to fill the chart and made to look like a spike. */
  minTop?: number;
  /** ...and never above this, e.g. 1 for a share. */
  maxTop?: number;
  compact?: boolean;
  testId?: string;
}

/** Request over limit above which their two labels would sit on each other. */
const CROWDED_RATIO = 0.85;

const CHART_CONFIG = {
  value: { label: "Usage", color: "var(--ink-3)" },
} satisfies ChartConfig;

/**
 * One reading over time. A reading that is missing is left as a gap rather than drawn
 * as zero: a stopped agent and an idle one must not look alike.
 */
const UsageAreaChart = memo(function UsageAreaChart({
  points,
  range,
  label,
  format,
  limit,
  request,
  minTop,
  maxTop,
  compact,
  testId,
}: UsageAreaChartProps) {
  const height = compact ? "h-[120px]" : "h-[200px]";
  const highest = useMemo(
    () => points.reduce((top, point) => Math.max(top, point.value ?? 0), 0),
    [points],
  );
  if (!points.some((point) => point.value !== null)) {
    return <EmptyChart>No readings in this period.</EmptyChart>;
  }

  // With a limit, the axis ends on it, so its label is the limit and not a rounded-up
  // neighbour. Without one, a little headroom keeps the line off the top edge.
  const wanted = limit ? Math.max(limit, request ?? 0, highest) : Math.max(request ?? 0, highest) * 1.1;
  const top = Math.min(Math.max(wanted, minTop ?? 0), maxTop ?? Number.POSITIVE_INFINITY) || 1;
  // A label is about 12px tall. Within this share of the limit the two lines are closer than that.
  const crowded = !!limit && !!request && request / limit > CROWDED_RATIO;

  return (
    <div data-testid={testId} aria-label={label} role="img">
      <ChartContainer config={CHART_CONFIG} className={`${height} w-full`}>
        {/* The right margin is room for the last time label, which is centred on the
            final point and would otherwise be cut off. */}
        <AreaChart data={points} margin={{ top: 8, right: 28, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="bucket"
            tickFormatter={(value: string) => formatUsageTick(value, range)}
            tickLine={false}
            axisLine={false}
            // Evenly spaced, and as many as fit without touching: a fixed count crowds a
            // phone-width chart, and a compact one, that a wide chart has room for.
            interval="equidistantPreserveStart"
            minTickGap={24}
            tick={{ fontSize: 11 }}
          />
          <YAxis
            tickLine={false}
            axisLine={false}
            width={64}
            tickCount={compact ? 3 : 5}
            domain={[0, top]}
            tickFormatter={format}
            tick={{ fontSize: 11 }}
          />
          <ChartTooltip
            content={
              <ChartTooltipContent
                labelFormatter={(value) => formatUsageTooltipTime(String(value))}
                formatter={(value) => format(Number(value))}
              />
            }
          />
          {limit ? (
            <ReferenceLine
              y={limit}
              stroke="var(--err)"
              strokeDasharray="4 4"
              label={{
                value: "Limit",
                // Under its line at the left, like "Request". Too close to the request for two
                // labels to stack, it goes to the right instead, where nothing else is.
                position: crowded ? "insideTopRight" : "insideTopLeft",
                fontSize: 11,
                fill: "var(--ink-4)",
              }}
            />
          ) : null}
          {request ? (
            <ReferenceLine
              y={request}
              stroke="var(--ink-3)"
              strokeDasharray="2 4"
              label={{ value: "Request", position: "insideTopLeft", fontSize: 11, fill: "var(--ink-4)" }}
            />
          ) : null}
          <Area
            dataKey="value"
            type="monotone"
            connectNulls={false}
            stroke="var(--color-value)"
            fill="var(--color-value)"
            fillOpacity={0.15}
            strokeWidth={2}
            isAnimationActive={false}
          />
        </AreaChart>
      </ChartContainer>
    </div>
  );
});

interface SeriesChartProps {
  series: ResourceUsagePoint[];
  range: ResourceUsageRange;
  compact?: boolean;
  testId?: string;
}

export const MemoryChart = memo(function MemoryChart({
  series,
  range,
  limitBytes,
  requestBytes = null,
  compact,
  testId,
}: SeriesChartProps & { limitBytes: number | null; requestBytes?: number | null }) {
  const points = useMemo(
    () => series.map((point) => ({ bucket: point.bucket, value: point.memoryWorkingSetBytes })),
    [series],
  );
  return (
    <UsageAreaChart
      points={points}
      range={range}
      label="Memory over time"
      format={formatBytes}
      limit={limitBytes}
      request={requestBytes}
      compact={compact}
      testId={testId}
    />
  );
});

export const CpuChart = memo(function CpuChart({
  series,
  range,
  limitCores,
  requestCores = null,
  compact,
  testId,
}: SeriesChartProps & { limitCores: number | null; requestCores?: number | null }) {
  const points = useMemo(
    () => series.map((point) => ({ bucket: point.bucket, value: point.cpuCores })),
    [series],
  );
  return (
    <UsageAreaChart
      points={points}
      range={range}
      label="CPU over time"
      format={formatCores}
      limit={limitCores}
      request={requestCores}
      compact={compact}
      testId={testId}
    />
  );
});

export const ThrottlingChart = memo(function ThrottlingChart({
  series,
  range,
  compact,
  testId,
}: SeriesChartProps) {
  const points = useMemo(
    () => series.map((point) => ({ bucket: point.bucket, value: point.cpuThrottledRatio })),
    [series],
  );
  return (
    <UsageAreaChart
      points={points}
      range={range}
      label="CPU throttling over time"
      format={formatShare}
      minTop={0.1}
      maxTop={1}
      compact={compact}
      testId={testId}
    />
  );
});
