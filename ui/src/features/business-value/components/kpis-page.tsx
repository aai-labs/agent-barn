"use client";

import { useCallback, useMemo } from "react";

import { DateRangePicker } from "@/components/date-range-picker";
import { formatWindowLabel } from "@/features/costs/format";
import { useCostUrlFilters } from "@/features/costs/hooks/use-cost-url-filters";
import { useRequireOrgManager } from "@/features/organizations/hooks/use-require-org-manager";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";

import { FILTER_DEFAULTS } from "../constants";
import { useOrganizationActivity } from "../hooks/use-organization-activity";
import { useOrganizationValue } from "../hooks/use-organization-value";
import { costsHref, type KpiWindow } from "../utils";
import { AgentKpiTable } from "./agent-kpi-table";
import { KpiFootnotes } from "./kpi-footnotes";
import { KpiTiles } from "./kpi-tiles";
import { KpiTrendChart } from "./kpi-trend-chart";

export function KpisPage() {
  const canManage = useRequireOrgManager();

  if (!canManage) return null;

  return <KpiDashboard />;
}

function KpiDashboard() {
  const { selectedOrganization } = useOrganizationContext();
  const [urlFilters, setUrlFilters] = useCostUrlFilters(FILTER_DEFAULTS);

  const range: KpiWindow = useMemo(
    () => ({
      fromDate: urlFilters.from || undefined,
      toDate: urlFilters.to || undefined,
    }),
    [urlFilters],
  );

  const { value, valueError, refetchValue } = useOrganizationValue(range);
  const { activity, activityError, refetchActivity } = useOrganizationActivity(range);

  const handleDateRangeChange = useCallback(
    (from: string, to: string) => {
      setUrlFilters({ from: from || null, to: to || null });
    },
    [setUrlFilters],
  );

  const valueSource = { data: value, error: valueError, onRetry: () => void refetchValue() };
  const activitySource = {
    data: activity,
    error: activityError,
    onRetry: () => void refetchActivity(),
  };
  const echoed = value ?? activity;
  const orgBase = `/dashboard/${selectedOrganization?.id ?? ""}`;

  return (
    <div className="max-w-[1200px] mx-auto px-10 pt-9 pb-24">
      <div className="flex flex-wrap items-start justify-between gap-3 mb-7">
        <div>
          <h1
            className="text-[28px] font-semibold tracking-tight m-0 mb-1"
            style={{ color: "var(--ink)" }}
          >
            KPIs
          </h1>
          <p className="text-[14px] m-0" style={{ color: "var(--ink-3)" }}>
            The value your agents produce against what they cost, and how reliably they work.
          </p>
          <p
            className="text-[13px] m-0 mt-1"
            style={{ color: "var(--ink-4)" }}
            data-testid="kpi-window"
          >
            {echoed
              ? formatWindowLabel(echoed.period, echoed.fromDate, echoed.toDate)
              : " "}
          </p>
        </div>
        <DateRangePicker
          from={urlFilters.from}
          to={urlFilters.to}
          onChange={handleDateRangeChange}
          placeholder="Last 30 days"
          width="16rem"
          ariaLabel="Date range"
        />
      </div>

      <KpiTiles
        value={valueSource}
        activity={activitySource}
        spendHref={costsHref(orgBase, urlFilters.from, urlFilters.to)}
      />

      <KpiTrendChart value={valueSource} activity={activitySource} />

      <AgentKpiTable value={valueSource} activity={activitySource} />

      <KpiFootnotes value={valueSource} />
    </div>
  );
}
