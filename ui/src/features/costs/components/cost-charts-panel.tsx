"use client";

import { Skeleton } from "@/components/ui/skeleton";

import type { CostSummary } from "../schemas";
import { CostHistogramChart } from "./cost-histogram-chart";
import { PromptTokensChart } from "./prompt-tokens-chart";
import { SpendByAgentChart } from "./spend-by-agent-chart";
import { SpendOverTimeChart } from "./spend-over-time-chart";

interface CostChartsPanelProps {
  summary: CostSummary | null;
  isLoading: boolean;
}

/** The four charts, in the order a reader needs them: how much, per agent, how
 *  big the prompts were, and how the per-call cost is distributed. */
export function CostChartsPanel({ summary, isLoading }: CostChartsPanelProps) {
  if (isLoading || !summary) {
    return (
      <div className="grid gap-4 mb-6 lg:grid-cols-2" data-testid="cost-charts-skeleton">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="af-card p-4">
            <Skeleton className="h-4 w-32 mb-4" />
            <Skeleton className="h-[220px] w-full" />
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="grid gap-4 mb-6 lg:grid-cols-2">
      <ChartCard title="Spend over time">
        <SpendOverTimeChart
          series={summary.spendOverTime}
          granularity={summary.granularity}
        />
      </ChartCard>

      <ChartCard title="Spend by agent">
        <SpendByAgentChart
          series={summary.spendByAgentOverTime}
          granularity={summary.granularity}
        />
      </ChartCard>

      <ChartCard title="Average prompt tokens">
        <PromptTokensChart
          series={summary.avgPromptTokensOverTime}
          granularity={summary.granularity}
        />
      </ChartCard>

      <ChartCard
        title="Cost per call"
        subtitle="Calls whose cost has not been recovered yet sit in the cheapest band."
      >
        <CostHistogramChart buckets={summary.costPerCallHistogram} />
      </ChartCard>
    </div>
  );
}

function ChartCard({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="af-card p-4">
      <h2
        className="text-[14px] font-semibold m-0 mb-1"
        style={{ color: "var(--ink)" }}
      >
        {title}
      </h2>
      {subtitle && (
        <p className="text-[12px] m-0 mb-3" style={{ color: "var(--ink-4)" }}>
          {subtitle}
        </p>
      )}
      {!subtitle && <div className="mb-3" />}
      {children}
    </div>
  );
}
