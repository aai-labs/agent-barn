"use client";

import { Area, AreaChart, CartesianGrid, XAxis, YAxis } from "recharts";

import {
  type ChartConfig,
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EmptyChart } from "@/features/costs/components/spend-over-time-chart";
import { formatSpendCompact } from "@/features/costs/format";
import type { Granularity } from "@/features/costs/schemas";
import { formatBucket, formatBucketLong } from "@/features/platform-stats/format";
import { evenlySpacedTicks } from "@/features/platform-stats/ticks";

import type { OrganizationActivity, OrganizationValue } from "../schemas";
import { type KpiSource, RetryButton } from "./kpi-tiles";

const VALUE_CHART_CONFIG = {
  value: { label: "Value", color: "var(--ink)" },
  spend: { label: "LLM spend", color: "var(--ink-4)" },
} satisfies ChartConfig;

const REQUESTS_CHART_CONFIG = {
  requests: { label: "Requests", color: "var(--ink-3)" },
} satisfies ChartConfig;

export function KpiTrendChart({
  value,
  activity,
}: {
  value: KpiSource<OrganizationValue>;
  activity: KpiSource<OrganizationActivity>;
}) {
  return (
    <div className="af-card mb-6 p-4" data-testid="kpi-trend">
      <h2 className="m-0 mb-3 text-[14px] font-semibold" style={{ color: "var(--ink)" }}>
        Trend
      </h2>
      <Tabs defaultValue="value">
        <TabsList>
          <TabsTrigger value="value">Value vs spend</TabsTrigger>
          <TabsTrigger value="requests">Requests</TabsTrigger>
        </TabsList>
        <TabsContent value="value">
          <SourceChart source={value}>
            {(data) => <ValueChart data={data} />}
          </SourceChart>
        </TabsContent>
        <TabsContent value="requests">
          <SourceChart source={activity}>
            {(data) => <RequestsChart data={data} />}
          </SourceChart>
        </TabsContent>
      </Tabs>
    </div>
  );
}

function SourceChart<T>({
  source,
  children,
}: {
  source: KpiSource<T>;
  children: (data: T) => React.ReactNode;
}) {
  if (source.error) {
    return (
      <EmptyChart>
        <span className="flex flex-col items-center gap-1">
          Unable to load
          <RetryButton onRetry={source.onRetry} />
        </span>
      </EmptyChart>
    );
  }
  if (!source.data) {
    return (
      <div data-testid="kpi-chart-skeleton">
        <Skeleton className="h-[220px] w-full" />
      </div>
    );
  }
  return children(source.data);
}

function ValueChart({ data }: { data: OrganizationValue }) {
  const rateIsSet = data.totals.hourlyRateUsd !== null;
  return (
    <div data-testid="kpi-value-chart">
      {!rateIsSet && (
        <p className="m-0 mb-2 text-[12px]" style={{ color: "var(--ink-4)" }}>
          Set an hourly rate to chart value
        </p>
      )}
      <ChartContainer config={VALUE_CHART_CONFIG} className="h-[220px] w-full">
        <AreaChart data={data.series} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis {...bucketAxisProps(data.series, data.granularity)} />
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
                labelFormatter={(label) => formatBucketLong(String(label), data.granularity)}
                formatter={(amount) => formatSpendCompact(Number(amount))}
              />
            }
          />
          <ChartLegend content={<ChartLegendContent />} verticalAlign="top" />
          {rateIsSet && (
            <Area
              dataKey="value"
              type="monotone"
              stroke="var(--color-value)"
              fill="var(--color-value)"
              fillOpacity={0.12}
              strokeWidth={2}
              isAnimationActive={false}
            />
          )}
          <Area
            dataKey="spend"
            type="monotone"
            stroke="var(--color-spend)"
            fill="var(--color-spend)"
            fillOpacity={0.12}
            strokeWidth={2}
            isAnimationActive={false}
          />
        </AreaChart>
      </ChartContainer>
    </div>
  );
}

function RequestsChart({ data }: { data: OrganizationActivity }) {
  return (
    <div data-testid="kpi-requests-chart">
      <ChartContainer config={REQUESTS_CHART_CONFIG} className="h-[220px] w-full">
        <AreaChart
          data={data.requestsSeries}
          margin={{ top: 8, right: 16, left: 0, bottom: 0 }}
        >
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis {...bucketAxisProps(data.requestsSeries, data.granularity)} />
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
                labelFormatter={(label) => formatBucketLong(String(label), data.granularity)}
              />
            }
          />
          <Area
            dataKey="requests"
            type="monotone"
            stroke="var(--color-requests)"
            fill="var(--color-requests)"
            fillOpacity={0.15}
            strokeWidth={2}
            isAnimationActive={false}
          />
        </AreaChart>
      </ChartContainer>
    </div>
  );
}

function bucketAxisProps(series: { bucket: string }[], granularity: Granularity) {
  return {
    dataKey: "bucket",
    tickFormatter: (bucket: string) => formatBucket(bucket, granularity),
    tickLine: false,
    axisLine: false,
    ticks: evenlySpacedTicks(series.map((point) => point.bucket)),
    interval: 0,
    tick: { fontSize: 11 },
  };
}
