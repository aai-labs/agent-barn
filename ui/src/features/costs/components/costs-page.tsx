"use client";

import { useCallback, useMemo } from "react";
import { RefreshCw } from "lucide-react";

import { useRequireOrgManager } from "@/features/organizations/hooks/use-require-org-manager";

import { useCostFilterOptions } from "../hooks/use-cost-filter-options";
import { useCostSummary } from "../hooks/use-cost-summary";
import { useCosts } from "../hooks/use-costs";
import { useAgentSpend } from "../hooks/use-agent-spend";
import { useCostUrlFilters } from "../hooks/use-cost-url-filters";
import type { CostFilters } from "../utils";
import { AgentsBySpend } from "./agents-by-spend";
import { CostChartsPanel } from "./cost-charts-panel";
import { CostFilterBar } from "./cost-filter-bar";
import { CostList } from "./cost-list";
import { CostSummaryCards } from "./cost-summary-cards";

const FILTER_DEFAULTS = {
  q: "",
  agentId: "",
  model: "",
  from: "",
  to: "",
  sort: "newest_first",
};

export function CostsPage() {
  // Costs are owner/admin-only; a member who lands here (e.g. by switching org)
  // is redirected to the org home.
  const canManage = useRequireOrgManager();

  const [urlFilters, setUrlFilters] = useCostUrlFilters(FILTER_DEFAULTS);

  // Memoised: an object rebuilt every render would change the query key every
  // render, and every hook below would refetch forever.
  const filters: CostFilters = useMemo(
    () => ({
      search: urlFilters.q || undefined,
      agentId: urlFilters.agentId || undefined,
      model: urlFilters.model || undefined,
      fromDate: urlFilters.from || undefined,
      toDate: urlFilters.to || undefined,
      sort: urlFilters.sort as CostFilters["sort"],
    }),
    [urlFilters],
  );

  const hasActiveFilters = !!(
    filters.search ||
    filters.agentId ||
    filters.model ||
    filters.fromDate ||
    filters.toDate
  );

  // The table lists every agent, so it deliberately drops the agent dimension:
  // filtering it by the selected agent would collapse it to the row just clicked.
  const agentTableFilters: CostFilters = useMemo(
    () => ({ ...filters, agentId: undefined }),
    [filters],
  );
  const { agents, isLoadingAgents } = useAgentSpend(agentTableFilters);

  const { summary, isLoading: isLoadingSummary, refetch: refetchSummary } =
    useCostSummary(filters);
  const { agentOptions, modelOptions } = useCostFilterOptions(filters);
  const {
    records,
    total,
    isLoading,
    isFetchingNextPage,
    isFetchingNextPageError,
    hasNextPage,
    fetchNextPage,
    error,
    refetch,
  } = useCosts(filters);

  const handleChange = useCallback(
    (key: keyof typeof urlFilters, value: string | null) => {
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
    setUrlFilters({ q: null, agentId: null, model: null, from: null, to: null });
  }, [setUrlFilters]);

  const handleRefresh = useCallback(() => {
    void refetchSummary();
    void refetch();
    window.scrollTo({ top: 0 });
  }, [refetchSummary, refetch]);

  if (!canManage) return null;

  return (
    <div className="max-w-[1200px] mx-auto px-10 pt-9 pb-24">
      <div className="flex flex-wrap items-start justify-between gap-3 mb-7">
        <div>
          <h1
            className="text-[28px] font-semibold tracking-tight m-0 mb-1"
            style={{ color: "var(--ink)" }}
          >
            Costs
          </h1>
          <p className="text-[14px] m-0" style={{ color: "var(--ink-3)" }}>
            What your agents spent on model calls, and where it went.
          </p>
        </div>
        <button className="af-btn flex-shrink-0" onClick={handleRefresh}>
          <RefreshCw size={14} /> Refresh
        </button>
      </div>

      <CostSummaryCards summary={summary} isLoading={isLoadingSummary} />

      <CostFilterBar
        values={urlFilters}
        agentOptions={agentOptions}
        modelOptions={modelOptions}
        onChange={handleChange}
        onDateRangeChange={handleDateRangeChange}
        hasActiveFilters={hasActiveFilters}
        onClear={handleClear}
      />

      <CostChartsPanel summary={summary} isLoading={isLoadingSummary} />

      <AgentsBySpend
        agents={agents}
        isLoading={isLoadingAgents}
        selectedAgentId={filters.agentId}
        onSelectAgent={(agentId) => setUrlFilters({ agentId })}
      />

      <p className="text-[13px] mb-3" style={{ color: "var(--ink-4)" }}>
        {total.toLocaleString()} {total === 1 ? "call" : "calls"}
      </p>

      <CostList
        records={records}
        isLoading={isLoading}
        error={isFetchingNextPageError ? undefined : error}
        onRetry={() => void refetch()}
        hasActiveFilters={hasActiveFilters}
        hasNextPage={hasNextPage}
        fetchNextPage={() => void fetchNextPage()}
        isFetchingNextPage={isFetchingNextPage}
        isFetchingNextPageError={isFetchingNextPageError}
      />

      {isFetchingNextPageError && (
        <p
          className="py-4 text-center text-[13px]"
          style={{ color: "var(--err)" }}
        >
          Unable to load more calls.{" "}
          <button
            type="button"
            className="underline"
            onClick={() => void fetchNextPage()}
          >
            Try again
          </button>
        </p>
      )}
    </div>
  );
}
