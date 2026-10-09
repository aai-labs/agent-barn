"use client";

import { parseAsStringEnum, useQueryState } from "nuqs";
import { TriangleAlert } from "lucide-react";

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
import { ChartCard } from "@/features/costs/components/cost-charts-panel";
import { formatPercent } from "@/features/costs/format";
import { useAgentRuntimeDiagnostics } from "@/features/agents/hooks/use-agent-runtime-diagnostics";
import type { Agent } from "@/features/agents/schemas";

import { formatBytes, formatCores } from "../format";
import { useAgentResourceUsage } from "../hooks/use-agent-resource-usage";
import type { AgentResourceUsage, ResourceUsageRange } from "../schemas";
import {
  DEFAULT_USAGE_RANGE,
  meterTone,
  RESOURCE_USAGE_RANGES,
  THROTTLING_WARN_RATIO,
  usageRatio,
} from "../utils";
import { CpuChart, MemoryChart, ThrottlingChart } from "./resource-usage-charts";
import { ResourceUsageNotice } from "./resource-usage-notice";
import { UsageStatCard } from "./usage-stat-card";

const RANGE_VALUES = RESOURCE_USAGE_RANGES.map((range) => range.value);
const STAT_GRID_STYLE = { gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" };
// min(..., 100%) keeps a column from being wider than the screen it is on.
const CHART_GRID_STYLE = { gridTemplateColumns: "repeat(auto-fit, minmax(min(420px, 100%), 1fr))" };

interface AgentResourceUsageTabProps {
  agent: Agent;
  /** Lets the out-of-memory callout point at the Activity tab, which holds the logs. */
  onOpenActivity?: () => void;
}

/**
 * CPU and memory of one Agent's container against the limits it runs with.
 *
 * Gated on `activity.read` by the page, the same as runtime diagnostics: both say how
 * the container is doing.
 */
export function AgentResourceUsageTab({ agent, onOpenActivity }: AgentResourceUsageTabProps) {
  const [range, setRange] = useQueryState(
    "range",
    parseAsStringEnum<ResourceUsageRange>(RANGE_VALUES)
      .withDefault(DEFAULT_USAGE_RANGE)
      .withOptions({ scroll: false, history: "replace" }),
  );
  const { usage, isLoadingUsage, isFetching, error, refetch } = useAgentResourceUsage(
    agent.id,
    range,
  );
  const rangeLabel =
    RESOURCE_USAGE_RANGES.find((option) => option.value === range)?.label.toLowerCase() ?? range;
  // A stopped Agent has no container, so there is nothing for diagnostics to say.
  const hasContainer = agent.status === "RUNNING" || agent.status === "ERROR";

  return (
    <div className="flex flex-col gap-6" data-testid="agent-resource-usage-tab">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h2 className="m-0 text-[15px] font-semibold" style={{ color: "var(--ink)" }}>
            Resource usage
          </h2>
          <p className="m-0 mt-0.5 text-[12.5px]" style={{ color: "var(--ink-4)" }}>
            CPU and memory of this agent&apos;s container, against the limits it runs with.
          </p>
        </div>
        <Select value={range} onValueChange={(value) => void setRange(value as ResourceUsageRange)}>
          <SelectTrigger
            className="af-input !h-auto"
            style={{ width: "12rem" }}
            aria-label="Time range"
            data-testid="resource-usage-range"
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
      </div>

      {isLoadingUsage && <UsageSkeleton />}

      {error && (
        <AppErrorState
          error={error}
          title="We couldn't load resource usage"
          description="You may not have access to this agent's resource usage, or the service is unavailable."
          onRetry={() => {
            void refetch();
          }}
          retryLabel="Retry"
          className="min-h-[10rem] p-0"
        />
      )}

      {usage && (
        <>
          <ResourceUsageNotice
            availability={usage.availability}
            state={usage.state}
            onRetry={() => {
              void refetch();
            }}
            isRetrying={isFetching}
          />
          {usage.availability === "available" && usage.state === "reporting" && (
            <>
              {hasContainer && (
                <OomKilledCallout
                  agentId={agent.id}
                  limitBytes={usage.memoryLimitBytes}
                  onOpenActivity={onOpenActivity}
                />
              )}
              <UsageStats usage={usage} rangeLabel={rangeLabel} />
              <div className="grid gap-3" style={CHART_GRID_STYLE}>
                <ChartCard
                  title="Memory"
                  subtitle={`In use, excluding cache.${requestAndLimit(
                    usage.memoryRequestBytes,
                    usage.memoryLimitBytes,
                    formatBytes,
                  )}`}
                  testId="resource-usage-memory-chart"
                >
                  <MemoryChart
                    series={usage.series}
                    range={usage.range}
                    limitBytes={usage.memoryLimitBytes}
                    requestBytes={usage.memoryRequestBytes}
                  />
                </ChartCard>
                <ChartCard
                  title="CPU"
                  subtitle={`${
                    usage.cpuAverageCores !== null
                      ? `Cores in use. Average ${formatCores(usage.cpuAverageCores)} over ${rangeLabel}.`
                      : "Cores in use."
                  }${requestAndLimit(usage.cpuRequestCores, usage.cpuLimitCores, formatCores)}`}
                  testId="resource-usage-cpu-chart"
                >
                  <CpuChart
                    series={usage.series}
                    range={usage.range}
                    limitCores={usage.cpuLimitCores}
                    requestCores={usage.cpuRequestCores}
                  />
                </ChartCard>
                <ChartCard
                  title="CPU throttling"
                  subtitle="Share of the time the agent was held back at its CPU limit."
                  testId="resource-usage-throttling-chart"
                >
                  <ThrottlingChart series={usage.series} range={usage.range} />
                </ChartCard>
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}

/** " Request X, limit Y." for a chart subtitle: what is known, in that order, or nothing. */
function requestAndLimit(request: number | null, limit: number | null, format: (value: number) => string): string {
  const parts = [
    request !== null ? `Request ${format(request)}` : null,
    limit !== null ? `${request !== null ? "limit" : "Limit"} ${format(limit)}` : null,
  ].filter((part): part is string => part !== null);
  return parts.length > 0 ? ` ${parts.join(", ")}.` : "";
}

function UsageStats({ usage, rangeLabel }: { usage: AgentResourceUsage; rangeLabel: string }) {
  const memoryRatio = usageRatio(usage.memoryWorkingSetBytes, usage.memoryLimitBytes);
  const peakRatio = usageRatio(usage.memoryPeakBytes, usage.memoryLimitBytes);
  const cpuRatio = usageRatio(usage.cpuCores, usage.cpuLimitCores);
  const throttled = usage.cpuThrottledRatio;

  return (
    <div className="grid gap-3" style={STAT_GRID_STYLE}>
      <UsageStatCard
        label="Memory now"
        value={usage.memoryWorkingSetBytes !== null ? formatBytes(usage.memoryWorkingSetBytes) : "—"}
        hint={
          usage.memoryRequestBytes !== null && usage.memoryLimitBytes !== null
            ? `of ${formatBytes(usage.memoryRequestBytes)} request, ${formatBytes(usage.memoryLimitBytes)} limit`
            : usage.memoryLimitBytes !== null && memoryRatio !== null
              ? `${formatPercent(memoryRatio)} of ${formatBytes(usage.memoryLimitBytes)} limit`
              : "no limit set"
        }
        tone={meterTone(memoryRatio)}
        testId="resource-usage-memory-now"
      />
      <UsageStatCard
        label="Peak memory"
        value={usage.memoryPeakBytes !== null ? formatBytes(usage.memoryPeakBytes) : "—"}
        hint={
          peakRatio !== null
            ? `${formatPercent(peakRatio)} of limit, ${rangeLabel}`
            : rangeLabel
        }
        tone={meterTone(peakRatio)}
        testId="resource-usage-memory-peak"
      />
      <UsageStatCard
        label="CPU now"
        value={usage.cpuCores !== null ? `${formatCores(usage.cpuCores)} cores` : "—"}
        hint={
          usage.cpuRequestCores !== null && usage.cpuLimitCores !== null
            ? `of ${formatCores(usage.cpuRequestCores)} cores request, ${formatCores(usage.cpuLimitCores)} cores limit, 5-minute average`
            : usage.cpuLimitCores !== null
              ? `of ${formatCores(usage.cpuLimitCores)} cores limit, 5-minute average`
              : "5-minute average"
        }
        tone={meterTone(cpuRatio)}
        testId="resource-usage-cpu-now"
      />
      <UsageStatCard
        label="CPU throttled"
        value={throttled !== null ? formatPercent(throttled) : "—"}
        hint={`of the time at its CPU limit, ${rangeLabel}`}
        tone={throttled !== null && throttled >= THROTTLING_WARN_RATIO ? "warn" : "ok"}
        testId="resource-usage-cpu-throttled"
      />
    </div>
  );
}

/**
 * Says so when the last container was killed for running out of memory.
 *
 * Reads the same diagnostics as the Activity tab, so it costs no extra request when that
 * tab has been open. The logs that explain why are there, hence the link.
 */
function OomKilledCallout({
  agentId,
  limitBytes,
  onOpenActivity,
}: {
  agentId: string;
  limitBytes: number | null;
  onOpenActivity?: () => void;
}) {
  const { data } = useAgentRuntimeDiagnostics(agentId);
  if (data?.terminationReason !== "OOMKilled") return null;

  return (
    <div
      className="af-card flex flex-col gap-3 p-4 sm:flex-row sm:items-start sm:justify-between"
      role="alert"
      style={{ borderColor: "var(--err)" }}
      data-testid="resource-usage-oom"
    >
      <div className="flex min-w-0 items-start gap-3">
        <TriangleAlert size={18} className="mt-0.5 flex-shrink-0" style={{ color: "var(--err)" }} />
        <div className="min-w-0">
          <p className="m-0 text-[14px] font-semibold" style={{ color: "var(--ink)" }}>
            The agent ran out of memory and was restarted
          </p>
          <p className="m-0 mt-1 text-[13px] leading-relaxed" style={{ color: "var(--ink-3)" }}>
            Its last container was stopped for using more than its{" "}
            {limitBytes !== null ? `${formatBytes(limitBytes)} ` : ""}memory limit
            {data.finishedAt ? ` at ${new Date(data.finishedAt).toLocaleString()}` : ""}.
          </p>
        </div>
      </div>
      {onOpenActivity && (
        <button type="button" className="af-btn af-btn-sm flex-shrink-0 self-start" onClick={onOpenActivity}>
          See activity and logs
        </button>
      )}
    </div>
  );
}

function UsageSkeleton() {
  return (
    <div data-testid="resource-usage-skeleton">
      <div className="mb-6 grid gap-3" style={STAT_GRID_STYLE}>
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
