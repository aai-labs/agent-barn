"use client";

import { parseAsString, parseAsStringEnum, useQueryState } from "nuqs";
import { RefreshCw } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { OrganizationCombobox } from "@/components/organization-combobox";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { ChartCard } from "@/features/costs/components/cost-charts-panel";

import { formatBytes, formatCores } from "../format";
import { usePlatformResourceUsage } from "../hooks/use-platform-resource-usage";
import type { PlatformResourceUsage, ResourceUsageRange } from "../schemas";
import {
  DEFAULT_USAGE_RANGE,
  METER_CRITICAL_RATIO,
  RESOURCE_USAGE_RANGES,
  THROTTLING_WARN_RATIO,
  usageRatio,
} from "../utils";
import { CapacitySection } from "./capacity-section";
import { OrganizationsByUsage } from "./organizations-by-usage";
import { PlatformAgentsUsageTable } from "./platform-agents-usage-table";
import { CpuChart, MemoryChart } from "./resource-usage-charts";
import { ResourceUsageNotice } from "./resource-usage-notice";
import { UsageStatCard } from "./usage-stat-card";

const RANGE_VALUES = RESOURCE_USAGE_RANGES.map((range) => range.value);
const STAT_GRID_STYLE = { gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" };
// min(..., 100%) keeps a column from being wider than the screen it is on.
const CHART_GRID_STYLE = { gridTemplateColumns: "repeat(auto-fit, minmax(min(420px, 100%), 1fr))" };

/**
 * CPU and memory of every agent's container, across all organizations.
 *
 * Platform Administrators only. It reads the Platform's own endpoint, which names agents
 * and organizations from the database and carries no tenant content; see the ADR on
 * resource usage as Platform Oversight Data.
 */
export function PlatformResourceUsagePage() {
  const [range, setRange] = useQueryState(
    "range",
    parseAsStringEnum<ResourceUsageRange>(RANGE_VALUES)
      .withDefault(DEFAULT_USAGE_RANGE)
      .withOptions({ scroll: false, history: "replace" }),
  );
  const [orgId, setOrgId] = useQueryState("orgId", parseAsString.withOptions({ history: "replace" }));
  const [orgName, setOrgName] = useQueryState("orgName", parseAsString.withOptions({ history: "replace" }));
  const { usage, isLoadingUsage, isFetching, error, refetch } = usePlatformResourceUsage(range, orgId);

  const rangeLabel =
    RESOURCE_USAGE_RANGES.find((option) => option.value === range)?.label.toLowerCase() ?? range;

  const selectOrganization = (organization: { id: string; name: string } | null) => {
    void setOrgId(organization?.id ?? null);
    void setOrgName(organization?.name ?? null);
  };

  return (
    <div className="af-page" data-testid="platform-resource-usage-page">
      <div className="mb-7 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="m-0 mb-1 text-[28px] font-semibold tracking-tight" style={{ color: "var(--ink)" }}>
            Platform Resource Usage
          </h1>
          <p className="m-0 text-[14px]" style={{ color: "var(--ink-3)" }}>
            CPU and memory of every agent&apos;s container, across all organizations.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <OrganizationCombobox
            organizationId={orgId}
            organizationName={orgName}
            onChange={selectOrganization}
          />
          <Select value={range} onValueChange={(value) => void setRange(value as ResourceUsageRange)}>
            <SelectTrigger
              className="af-input !h-auto"
              style={{ width: "12rem" }}
              aria-label="Time range"
              data-testid="platform-usage-range"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {RESOURCE_USAGE_RANGES.map(({ value, label }) => (
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
          title="We couldn't load resource usage"
          description="Platform resource usage is unavailable right now."
          onRetry={() => {
            void refetch();
          }}
          retryLabel="Retry"
          className="min-h-[15rem] p-0"
        />
      ) : isLoadingUsage ? (
        <UsageSkeleton />
      ) : (
        usage && (
          <>
            {usage.availability !== "available" && (
              <div className="mb-4">
                <ResourceUsageNotice
                  availability={usage.availability}
                  state={null}
                  onRetry={() => {
                    void refetch();
                  }}
                  isRetrying={isFetching}
                />
              </div>
            )}
            <UsageStats usage={usage} />
            {/* Outside the availability check: the limits are in the database and stay editable. */}
            <CapacitySection capacity={usage.capacity} />
            {usage.availability === "available" && (
              <>
                <OrganizationsByUsage
                  organizations={usage.organizations}
                  activeOrganizationId={orgId}
                  onSelect={selectOrganization}
                />
                <div className="mb-6 grid gap-3" style={CHART_GRID_STYLE}>
                  <ChartCard
                    title="Memory"
                    subtitle="In use, excluding cache. Each agent's highest reading in a step, added up."
                    testId="platform-usage-memory-chart"
                  >
                    <MemoryChart series={usage.series} range={usage.range} limitBytes={null} />
                  </ChartCard>
                  <ChartCard
                    title="CPU"
                    subtitle={`Cores in use, all agents together, ${rangeLabel}.`}
                    testId="platform-usage-cpu-chart"
                  >
                    <CpuChart series={usage.series} range={usage.range} limitCores={null} />
                  </ChartCard>
                </div>
                <h2 className="m-0 mb-3 text-[14px] font-semibold" style={{ color: "var(--ink)" }}>
                  Heaviest agents
                </h2>
                <PlatformAgentsUsageTable agents={usage.agents} needUpdate={usage.totals.agentsRestartRequired ?? 0} />
                <p className="m-0 mt-3 text-[12.5px]" style={{ color: "var(--ink-4)" }}>
                  Readings are current, refreshed every minute. Charts cover the {rangeLabel}.
                </p>
              </>
            )}
          </>
        )
      )}
    </div>
  );
}

function UsageStats({ usage }: { usage: PlatformResourceUsage }) {
  const { totals, agents, organizations, organizationId } = usage;
  const measured = usage.availability === "available";

  // Containers with no live agent are in the platform totals, so the live count is
  // taken from those. A filtered view leaves them out of its totals already.
  const noLiveAgent = organizationId
    ? 0
    : (organizations.find((row) => row.organizationId === null)?.agentsReporting ?? 0);
  const reporting = measured && totals.agentsReporting !== null ? totals.agentsReporting - noLiveAgent : null;
  const needUpdate = totals.agentsRestartRequired ?? 0;

  const nearMemoryLimit = agents.filter(
    (agent) => (usageRatio(agent.memoryWorkingSetBytes, agent.memoryLimitBytes) ?? 0) >= METER_CRITICAL_RATIO,
  ).length;
  const heldBack = agents.filter(
    (agent) => (agent.cpuThrottledRatio ?? 0) >= THROTTLING_WARN_RATIO,
  ).length;

  const unknown = "—";
  // What the agents reporting are set to use, added up: the same agents as the figures
  // above, so each pair describes one thing. Namespace-wide figures are under Capacity.
  const across = reporting !== null ? `across the ${reporting} ${reporting === 1 ? "agent" : "agents"} reporting` : undefined;
  return (
    <>
      <div className="mb-3 grid gap-3" style={STAT_GRID_STYLE}>
        <UsageStatCard
          label="Memory in use"
          value={totals.memoryWorkingSetBytes !== null ? formatBytes(totals.memoryWorkingSetBytes) : unknown}
          hint={
            totals.memoryLimitBytes !== null ? `of ${formatBytes(totals.memoryLimitBytes)} in limits` : undefined
          }
          testId="platform-usage-memory"
        />
        <UsageStatCard
          label="CPU in use"
          value={totals.cpuCores !== null ? `${formatCores(totals.cpuCores)} cores` : unknown}
          hint={
            totals.cpuLimitCores !== null
              ? `of ${formatCores(totals.cpuLimitCores)} cores in limits, 5-minute average`
              : undefined
          }
          testId="platform-usage-cpu"
        />
        <UsageStatCard
          label="Agents reporting"
          value={reporting !== null ? String(reporting) : unknown}
          hint={`of ${totals.agentsWithContainer} running or in error${
            needUpdate > 0 ? ` · ${needUpdate} need an update` : ""
          }`}
          tone={reporting !== null && reporting < totals.agentsWithContainer ? "warn" : "ok"}
          testId="platform-usage-reporting"
        />
        <UsageStatCard
          label="Near memory limit"
          value={measured ? String(nearMemoryLimit) : unknown}
          hint="at 90% or more of their limit"
          tone={nearMemoryLimit > 0 ? "err" : "ok"}
          testId="platform-usage-near-limit"
        />
        <UsageStatCard
          label="Held back by CPU"
          value={measured ? String(heldBack) : unknown}
          hint="at their CPU limit often, last hour"
          tone={heldBack > 0 ? "warn" : "ok"}
          testId="platform-usage-throttled"
        />
      </div>
      <div className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4" data-testid="platform-usage-aggregates">
        <UsageStatCard
          label="Memory requested"
          value={totals.memoryRequestBytes !== null ? formatBytes(totals.memoryRequestBytes) : unknown}
          hint={across}
          testId="platform-usage-memory-requested"
        />
        <UsageStatCard
          label="Memory limits"
          value={totals.memoryLimitBytes !== null ? formatBytes(totals.memoryLimitBytes) : unknown}
          hint={across}
          testId="platform-usage-memory-limits"
        />
        <UsageStatCard
          label="CPU requested"
          value={totals.cpuRequestCores !== null ? `${formatCores(totals.cpuRequestCores)} cores` : unknown}
          hint={across}
          testId="platform-usage-cpu-requested"
        />
        <UsageStatCard
          label="CPU limits"
          value={totals.cpuLimitCores !== null ? `${formatCores(totals.cpuLimitCores)} cores` : unknown}
          hint={across}
          testId="platform-usage-cpu-limits"
        />
      </div>
    </>
  );
}

function UsageSkeleton() {
  return (
    <div data-testid="platform-usage-skeleton">
      <div className="mb-3 grid gap-3" style={STAT_GRID_STYLE}>
        {Array.from({ length: 5 }).map((_, index) => (
          <div key={index} className="af-card px-4 py-3.5">
            <Skeleton className="mb-2 h-3 w-16" />
            <Skeleton className="h-6 w-20" />
          </div>
        ))}
      </div>
      <div className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <div key={index} className="af-card px-4 py-3.5">
            <Skeleton className="mb-2 h-3 w-16" />
            <Skeleton className="h-6 w-20" />
          </div>
        ))}
      </div>
      <div className="grid gap-3" style={CHART_GRID_STYLE}>
        {Array.from({ length: 2 }).map((_, index) => (
          <div key={index} className="af-card p-4">
            <Skeleton className="h-[200px] w-full" />
          </div>
        ))}
      </div>
    </div>
  );
}
