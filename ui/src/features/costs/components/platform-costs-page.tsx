"use client";

import { useCallback, useMemo } from "react";
import { RefreshCw } from "lucide-react";

import { OrganizationCombobox } from "@/components/organization-combobox";

import { DEFAULT_COST_PERIOD } from "../constants";
import { formatSpend } from "../format";
import {
  usePlatformCostFilterOptions,
  usePlatformCostOrganizations,
  usePlatformCostSummary,
  usePlatformCosts,
} from "../hooks/use-platform-costs";
import { useCostUrlFilters } from "../hooks/use-cost-url-filters";
import type { CostFilters } from "../utils";
import { CostChartsPanel } from "./cost-charts-panel";
import { CostFilterBar } from "./cost-filter-bar";
import { CostList } from "./cost-list";
import { CostSummaryCards, StatCard } from "./cost-summary-cards";
import { OrganizationsBySpend } from "./organizations-by-spend";

const FILTER_DEFAULTS = {
  q: "",
  orgId: "",
  orgName: "",
  agentId: "",
  model: "",
  period: DEFAULT_COST_PERIOD,
  sort: "newest_first",
};

export function PlatformCostsPage() {
  const [urlFilters, setUrlFilters] = useCostUrlFilters(FILTER_DEFAULTS);

  const filters: CostFilters = useMemo(
    () => ({
      search: urlFilters.q || undefined,
      organizationId: urlFilters.orgId || undefined,
      agentId: urlFilters.agentId || undefined,
      model: urlFilters.model || undefined,
      period: urlFilters.period,
      sort: urlFilters.sort as CostFilters["sort"],
    }),
    [urlFilters],
  );

  const hasActiveFilters = !!(
    filters.search ||
    filters.organizationId ||
    filters.agentId ||
    filters.model
  );

  const { summary, isLoading: isLoadingSummary, refetch: refetchSummary } =
    usePlatformCostSummary(filters);
  const { agentOptions, modelOptions } = usePlatformCostFilterOptions(filters);
  const { organizations } = usePlatformCostOrganizations(filters);
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
  } = usePlatformCosts(filters);

  const handleChange = useCallback(
    (key: keyof typeof urlFilters, value: string | null) => {
      setUrlFilters({ [key]: value || null });
    },
    [setUrlFilters],
  );

  const handleOrganizationChange = useCallback(
    (organization: { id: string; name: string } | null) => {
      // Clearing the agent alongside it: the agent list is scoped by
      // organization, so a held-over selection would filter to an agent that is
      // no longer in the options and the table would read as empty for no
      // visible reason.
      setUrlFilters({
        orgId: organization?.id ?? null,
        orgName: organization?.name ?? null,
        agentId: null,
      });
    },
    [setUrlFilters],
  );

  const handleClear = useCallback(() => {
    setUrlFilters({
      q: null,
      orgId: null,
      orgName: null,
      agentId: null,
      model: null,
    });
  }, [setUrlFilters]);

  // Held stable so the memoised filter bar is not handed a fresh element tree
  // on every render, which would defeat the memo.
  const organizationFilter = useMemo(
    () => (
      <OrganizationCombobox
        organizationId={urlFilters.orgId || null}
        organizationName={urlFilters.orgName || null}
        onChange={handleOrganizationChange}
      />
    ),
    [urlFilters.orgId, urlFilters.orgName, handleOrganizationChange],
  );

  const handleRefresh = useCallback(() => {
    void refetchSummary();
    void refetch();
    window.scrollTo({ top: 0 });
  }, [refetchSummary, refetch]);

  return (
    <div className="max-w-[1200px] mx-auto px-10 pt-9 pb-24">
      <div className="flex flex-wrap items-start justify-between gap-3 mb-7">
        <div>
          <h1
            className="text-[28px] font-semibold tracking-tight m-0 mb-1"
            style={{ color: "var(--ink)" }}
          >
            Platform Costs
          </h1>
          <p className="text-[14px] m-0" style={{ color: "var(--ink-3)" }}>
            Model spend across every organization on the platform.
          </p>
        </div>
        <button className="af-btn flex-shrink-0" onClick={handleRefresh}>
          <RefreshCw size={14} /> Refresh
        </button>
      </div>

      <CostSummaryCards
        summary={summary}
        isLoading={isLoadingSummary}
        cardCount={8}
      >
        {summary && (
          <>
            <StatCard
              label="Burn rate"
              value={`${formatSpend(summary.dailyBurnRate)}/day`}
              hint="over this period"
              testId="cost-burn-rate"
            />
            <StatCard
              label="Runway"
              // Null covers "no credit limit set" and "the poll failed" alike.
              // Both are "we don't know", and neither should read as a number.
              value={
                summary.runwayDays === null
                  ? "Unknown"
                  : `${Math.floor(summary.runwayDays).toLocaleString()} days`
              }
              hint={
                summary.creditsRemaining === null
                  ? "no credit limit on the key"
                  : `${formatSpend(summary.creditsRemaining)} left`
              }
              testId="cost-runway"
            />
            <StatCard
              label="Unattributed"
              value={formatSpend(summary.unattributedSpend)}
              hint={`${summary.unattributedCalls.toLocaleString()} ${
                summary.unattributedCalls === 1 ? "call" : "calls"
              } with no agent`}
              testId="cost-unattributed"
            />
          </>
        )}
      </CostSummaryCards>

      <CostFilterBar
        values={urlFilters}
        agentOptions={agentOptions}
        modelOptions={modelOptions}
        onChange={handleChange}
        hasActiveFilters={hasActiveFilters}
        onClear={handleClear}
        organizationFilter={organizationFilter}
      />

      <OrganizationsBySpend
        organizations={organizations}
        activeOrganizationId={urlFilters.orgId || null}
        onSelect={handleOrganizationChange}
      />

      <CostChartsPanel summary={summary} isLoading={isLoadingSummary} />

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
        showOrganization
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
