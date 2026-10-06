"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { parseAsStringEnum, useQueryState } from "nuqs";
import { RefreshCw } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { formatWindowLabel } from "@/features/costs/format";

import { useAgentsOverview } from "../hooks/use-agents-overview";
import { DEFAULT_OVERVIEW_PERIOD, OVERVIEW_PERIODS, type OverviewPeriod } from "../utils";
import { AgentsOverviewTable } from "./agents-overview-table";
import { ResourceUsageNotice } from "./resource-usage-notice";

const PERIOD_VALUES: OverviewPeriod[] = OVERVIEW_PERIODS.map((period) => period.value);

/**
 * Every Agent the viewer can read, in one table: status, what it cost, and what it is
 * using right now, with the detail of each one row away.
 *
 * Scoped to the organization in the URL and to the viewer's own access, per Agent: a
 * figure they may not see is a dash, not a hidden row.
 */
export function AgentsOverviewPage() {
  const params = useParams();
  const orgId = typeof params?.orgId === "string" ? params.orgId : "";
  const [period, setPeriod] = useQueryState(
    "period",
    parseAsStringEnum<OverviewPeriod>(PERIOD_VALUES)
      .withDefault(DEFAULT_OVERVIEW_PERIOD)
      .withOptions({ scroll: false, history: "replace" }),
  );
  const { overview, isLoadingOverview, error, refetch } = useAgentsOverview(period);

  return (
    <div className="af-page" data-testid="agents-overview-page">
      <div className="mb-7 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1
            className="m-0 mb-1 text-[28px] font-semibold tracking-tight"
            style={{ color: "var(--ink)" }}
          >
            Usage
          </h1>
          <p className="m-0 text-[14px]" style={{ color: "var(--ink-3)" }}>
            Every agent you can see, what it costs, and what it is using.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Select value={period} onValueChange={(value) => void setPeriod(value as OverviewPeriod)}>
            <SelectTrigger
              className="af-input !h-auto"
              style={{ width: "10.5rem" }}
              aria-label="Spend period"
              data-testid="agents-overview-period"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {OVERVIEW_PERIODS.map(({ value, label }) => (
                  <SelectItem key={value} value={value}>
                    {label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
          <button className="af-btn flex-shrink-0" onClick={() => void refetch()}>
            <RefreshCw size={14} /> Refresh
          </button>
        </div>
      </div>

      {error ? (
        <AppErrorState
          error={error}
          title="We couldn't load your agents"
          description="The agents overview is unavailable right now."
          onRetry={() => {
            void refetch();
          }}
          retryLabel="Retry"
          className="min-h-[15rem] p-0"
        />
      ) : isLoadingOverview ? (
        <OverviewSkeleton />
      ) : (
        overview && (
          <>
            {overview.resourceUsageAvailability !== "available" && (
              <div className="mb-4">
                <ResourceUsageNotice
                  availability={overview.resourceUsageAvailability}
                  state={null}
                  onRetry={() => {
                    void refetch();
                  }}
                />
              </div>
            )}

            {overview.items.length === 0 ? (
              <div
                className="flex flex-col items-center justify-center rounded-2xl px-5 py-12 text-center"
                style={{ border: "1px dashed var(--line-strong)", color: "var(--ink-3)" }}
                data-testid="agents-overview-empty"
              >
                <div className="mb-1 text-[0.9375rem] font-medium" style={{ color: "var(--ink)" }}>
                  No agents yet
                </div>
                <div className="text-[0.844rem]">
                  Hire your first teammate from{" "}
                  <Link href={`/dashboard/${orgId}`} className="underline underline-offset-2">
                    Home
                  </Link>
                  .
                </div>
              </div>
            ) : (
              <>
                <AgentsOverviewTable items={overview.items} period={period} orgId={orgId} />
                <p className="m-0 mt-3 text-[12.5px]" style={{ color: "var(--ink-4)" }}>
                  Spend covers the{" "}
                  {formatWindowLabel(overview.period, overview.fromDate, overview.toDate)}. CPU and
                  memory are current readings, refreshed every minute.
                  {overview.total > overview.items.length &&
                    ` Showing ${overview.items.length} of ${overview.total} agents.`}
                </p>
              </>
            )}
          </>
        )
      )}
    </div>
  );
}

function OverviewSkeleton() {
  return (
    <div className="af-card p-4" data-testid="agents-overview-skeleton">
      {Array.from({ length: 4 }).map((_, index) => (
        <Skeleton key={index} className="mb-3 h-12 w-full last:mb-0" />
      ))}
    </div>
  );
}
