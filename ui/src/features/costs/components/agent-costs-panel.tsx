"use client";

import { useCallback, useMemo, useState } from "react";
import { format, formatDistanceToNowStrict } from "date-fns";
import { RefreshCw } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/shared/api/error/errors";

import {
  formatCallSpend,
  formatDuration,
  formatPercent,
  formatSpend,
  formatTokens,
} from "../format";
import {
  AGENT_CALLS_PAGE_SIZE,
  useAgentCost,
  useAgentCostCalls,
  useAgentCostModelOptions,
  useAgentMonthlyCosts,
  type AgentCostFilters,
} from "../hooks/use-agent-cost";
import { useCostUrlFilters } from "../hooks/use-cost-url-filters";
import type { AgentCost, MonthlyCost } from "../schemas";
import { AgentModelBreakdown } from "./agent-model-breakdown";
import { CallsOverTimeChart } from "./calls-over-time-chart";
import { CostCallsTable } from "./cost-calls-table";
import { ChartCard } from "./cost-charts-panel";
import { CostFilterBar, type CostFilterBarValues } from "./cost-filter-bar";
import { CostHistogramChart } from "./cost-histogram-chart";
import { StatCard } from "./cost-summary-cards";
import { MonthlyCosts } from "./monthly-costs";
import { PromptTokensChart } from "./prompt-tokens-chart";
import { SpendOverTimeChart } from "./spend-over-time-chart";

const FILTER_DEFAULTS = {
  q: "",
  model: "",
  from: "",
  to: "",
  sort: "newest_first",
};

const STAT_CARD_COUNT = 9;

/**
 * Everything known about one Agent's spend.
 *
 * Every read here goes through the Agent's own cost routes, which authorize
 * against its Agent Access Role. The Organization summary is not an option: it
 * needs an Organization-wide permission an Agent Viewer or Editor never has.
 *
 * The summary, the charts and the call list share one filter, so a card and the
 * table under it always count the same calls. The monthly section takes the same
 * filter but not the date range.
 */
export function AgentCostsPanel({ agentId }: { agentId: string }) {
  const [urlFilters, setUrlFilters] = useCostUrlFilters(FILTER_DEFAULTS);

  // Memoised: an object rebuilt every render would change the query key every
  // render, and every hook below would refetch forever.
  const filters: AgentCostFilters = useMemo(
    () => ({
      search: urlFilters.q || undefined,
      model: urlFilters.model || undefined,
      fromDate: urlFilters.from || undefined,
      toDate: urlFilters.to || undefined,
      sort: urlFilters.sort as AgentCostFilters["sort"],
    }),
    [urlFilters],
  );
  const hasActiveFilters = !!(
    filters.search ||
    filters.model ||
    filters.fromDate ||
    filters.toDate
  );

  const {
    agentCost,
    isLoadingAgentCost,
    error,
    refetch: refetchSummary,
  } = useAgentCost(agentId, filters);
  const { modelOptions } = useAgentCostModelOptions(agentId, filters);
  const monthly = useAgentMonthlyCosts(agentId, filters);

  // The page belongs to the filter it was reached under: any change of filter or
  // sort starts again at page one. Held beside the filter it was set for and
  // compared on render, rather than reset from an effect after the fact.
  const filterKey = JSON.stringify(filters);
  const [callsPage, setCallsPage] = useState({ filterKey, page: 1 });
  const page = callsPage.filterKey === filterKey ? callsPage.page : 1;
  const calls = useAgentCostCalls(agentId, filters, page);
  const handlePageChange = useCallback(
    (next: number) => setCallsPage({ filterKey, page: next }),
    [filterKey],
  );
  const handleSortChange = useCallback(
    (sort: string) => setUrlFilters({ sort }),
    [setUrlFilters],
  );

  const handleChange = useCallback(
    (key: keyof CostFilterBarValues, value: string | null) => {
      if (key === "agentId") return;
      setUrlFilters({ [key]: value || null });
    },
    [setUrlFilters],
  );
  const handleDateRangeChange = useCallback(
    (from: string, to: string) => {
      setUrlFilters({ from: from || null, to: to || null });
    },
    [setUrlFilters],
  );
  const handleClear = useCallback(() => {
    setUrlFilters({ q: null, model: null, from: null, to: null });
  }, [setUrlFilters]);

  const { refetch: refetchMonthly } = monthly;
  const { refetch: refetchCalls } = calls;
  const handleRefresh = useCallback(() => {
    void refetchSummary();
    void refetchMonthly();
    void refetchCalls();
  }, [refetchSummary, refetchMonthly, refetchCalls]);

  // With no range picked the server applies its own default window, so the
  // picker names the window it actually used rather than claiming "All dates".
  const resolvedWindowLabel = agentCost
    ? `${format(new Date(agentCost.fromDate), "MMM d, yyyy")} – ${format(
        new Date(agentCost.toDate),
        "MMM d, yyyy",
      )}`
    : "Loading…";

  if (error instanceof ApiError && error.status === 403) {
    // A reader without cost access on this Agent is not looking at a failure,
    // so it is not reported as one.
    return (
      <div
        className="af-card flex h-[200px] items-center justify-center text-[13px]"
        style={{ color: "var(--ink-4)" }}
      >
        You don&apos;t have access to this agent&apos;s costs.
      </div>
    );
  }

  return (
    <div data-testid="agent-costs">
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <CostFilterBar
            values={urlFilters}
            modelOptions={modelOptions}
            onChange={handleChange}
            onDateRangeChange={handleDateRangeChange}
            hasActiveFilters={hasActiveFilters}
            onClear={handleClear}
            searchPlaceholder="Search by model or request ID"
            datePlaceholder={resolvedWindowLabel}
            showSort={false}
          />
        </div>
        <button className="af-btn flex-shrink-0" onClick={handleRefresh}>
          <RefreshCw size={14} /> Refresh
        </button>
      </div>

      {error ? (
        <div
          className="af-card mb-6 flex h-[200px] items-center justify-center text-[13px]"
          style={{ color: "var(--ink-4)" }}
        >
          We couldn&apos;t load this agent&apos;s spend.
        </div>
      ) : isLoadingAgentCost || !agentCost ? (
        <AgentCostSkeleton />
      ) : (
        <>
          <AgentCostCards
            agentCost={agentCost}
            currentMonth={monthly.months?.find((m) => m.isCurrent) ?? null}
          />

          {agentCost.healedCalls > 0 && (
            <p
              className="text-[12px] -mt-3 mb-6"
              style={{ color: "var(--ink-4)" }}
              data-testid="agent-cost-healed-note"
            >
              {agentCost.healedCalls.toLocaleString()}{" "}
              {agentCost.healedCalls === 1 ? "call's" : "calls'"} cost was
              recovered from OpenRouter after the proxy missed it, so earlier
              totals for this period may have risen.
            </p>
          )}

          <div className="grid gap-4 mb-6 lg:grid-cols-2">
            <ChartCard title="Spend over time">
              <SpendOverTimeChart
                series={agentCost.spendOverTime}
                granularity={agentCost.granularity}
              />
            </ChartCard>
            <ChartCard title="Calls over time" testId="agent-calls-over-time">
              <CallsOverTimeChart
                series={agentCost.spendOverTime}
                granularity={agentCost.granularity}
              />
            </ChartCard>
            <ChartCard title="Average prompt tokens">
              <PromptTokensChart
                series={agentCost.avgPromptTokensOverTime}
                granularity={agentCost.granularity}
              />
            </ChartCard>
            <ChartCard
              title="Cost per call"
              subtitle="Each bar covers calls up to its label. Calls whose cost has not been recovered yet sit in the cheapest band."
            >
              <CostHistogramChart buckets={agentCost.costPerCallHistogram} />
            </ChartCard>
          </div>

          {agentCost.modelsBreakdown.length > 0 && (
            <AgentModelBreakdown
              models={agentCost.modelsBreakdown}
              totalCost={agentCost.totalCost}
            />
          )}
        </>
      )}

      <MonthlyCosts
        months={monthly.months}
        isLoading={monthly.isLoading}
        error={monthly.error}
        onRetry={() => void refetchMonthly()}
        showAgents={false}
      />

      <CostCallsTable
        records={calls.records}
        total={calls.total}
        page={page}
        pageSize={AGENT_CALLS_PAGE_SIZE}
        onPageChange={handlePageChange}
        sort={urlFilters.sort}
        onSortChange={handleSortChange}
        isLoading={calls.isLoading}
        isFetching={calls.isFetching}
        error={calls.error}
        onRetry={() => void refetchCalls()}
        hasActiveFilters={hasActiveFilters}
      />
    </div>
  );
}

function AgentCostCards({
  agentCost,
  currentMonth,
}: {
  agentCost: AgentCost;
  currentMonth: MonthlyCost | null;
}) {
  const failedShare =
    agentCost.totalCalls > 0 ? agentCost.failedCalls / agentCost.totalCalls : 0;

  return (
    <div
      className="grid gap-3 mb-6"
      style={{ gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}
    >
      <StatCard
        label="Total spend"
        value={formatSpend(agentCost.totalCost)}
        hint={`${agentCost.totalCalls.toLocaleString()} ${agentCost.totalCalls === 1 ? "call" : "calls"}`}
        testId="agent-cost-total-spend"
      />
      <StatCard
        label="Burn rate"
        value={`${formatSpend(agentCost.dailyBurnRate)}/day`}
        hint="over this period"
        testId="agent-cost-burn-rate"
      />
      <StatCard
        label="This month"
        value={currentMonth ? formatSpend(currentMonth.spend) : "—"}
        hint={
          currentMonth?.projectedSpend != null
            ? `on pace for ${formatSpend(currentMonth.projectedSpend)}`
            : "month to date"
        }
        testId="agent-cost-this-month"
      />
      <StatCard
        label="Cost per call"
        value={formatCallSpend(agentCost.avgCostPerCall)}
        hint="average"
        testId="agent-cost-per-call"
      />
      <StatCard
        label="Tokens"
        value={formatTokens(agentCost.totalTokens)}
        hint={`${formatTokens(agentCost.promptTokens)} in · ${formatTokens(agentCost.completionTokens)} out`}
        testId="agent-cost-tokens"
      />
      <StatCard
        label="Prompt tokens"
        value={formatTokens(agentCost.avgPromptTokens)}
        hint="average per call"
        testId="agent-cost-avg-prompt-tokens"
      />
      <StatCard
        label="Failed calls"
        value={agentCost.failedCalls.toLocaleString()}
        hint={`${formatPercent(failedShare)} of calls`}
        testId="agent-cost-failed-calls"
      />
      <StatCard
        label="Latency"
        value={
          agentCost.avgDurationMs === null
            ? "—"
            : formatDuration(Math.round(agentCost.avgDurationMs))
        }
        hint="average per call"
        testId="agent-cost-latency"
      />
      <StatCard
        label="Latest call"
        value={
          agentCost.lastCallAt
            ? `${formatDistanceToNowStrict(new Date(agentCost.lastCallAt))} ago`
            : "—"
        }
        hint={
          agentCost.firstCallAt
            ? `first in period ${format(new Date(agentCost.firstCallAt), "MMM d")}`
            : "no calls in this period"
        }
        testId="agent-cost-latest-call"
      />
    </div>
  );
}

function AgentCostSkeleton() {
  return (
    <div data-testid="agent-cost-skeleton">
      <div
        className="grid gap-3 mb-6"
        style={{ gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}
      >
        {Array.from({ length: STAT_CARD_COUNT }).map((_, i) => (
          <div key={i} className="af-card px-4 py-3.5">
            <Skeleton className="h-3 w-16 mb-2" />
            <Skeleton className="h-6 w-20" />
          </div>
        ))}
      </div>
      <div className="grid gap-4 mb-6 lg:grid-cols-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="af-card p-4">
            <Skeleton className="h-4 w-32 mb-4" />
            <Skeleton className="h-[220px] w-full" />
          </div>
        ))}
      </div>
    </div>
  );
}
