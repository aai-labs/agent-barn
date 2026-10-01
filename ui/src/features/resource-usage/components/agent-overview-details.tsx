"use client";

import Link from "next/link";
import { useMemo, type ReactNode } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { useAgent } from "@/features/agents/hooks/use-agent";
import { useAgentRuntimeDiagnostics } from "@/features/agents/hooks/use-agent-runtime-diagnostics";
import type { AgentHealth } from "@/features/agents/schemas";
import { StatusLine } from "@/features/agents/components/status-line";
import { canAgent, formatModelName } from "@/features/agents/utils";
import { useAgentCost } from "@/features/costs/hooks/use-agent-cost";
import { formatCallSpend, formatPercent, formatSpend } from "@/features/costs/format";

import { formatBytes, formatCores } from "../format";
import { useAgentResourceUsage } from "../hooks/use-agent-resource-usage";
import type { AgentOverviewItem } from "../schemas";
import { THROTTLING_WARN_RATIO, usageRatio, type OverviewPeriod } from "../utils";
import { MemoryChart } from "./resource-usage-charts";
import { noticeFor } from "./resource-usage-notice";
import { UsageMeter } from "./usage-meter";

const PANEL_GRID_STYLE = { gridTemplateColumns: "repeat(auto-fit, minmax(min(260px, 100%), 1fr))" };

interface AgentOverviewDetailsProps {
  item: AgentOverviewItem;
  health: AgentHealth | null;
  period: OverviewPeriod;
  /** `/dashboard/<org>/agents/<id>`; the full tabs hang off it as `?tab=`. */
  agentHref: string;
}

/**
 * The three things the overview row summarises, in full: status, cost and resource usage.
 *
 * Each panel reads what its own page reads, so the numbers here cannot disagree with the
 * ones behind the links. They load only once a row is opened, and only for the panels the
 * caller may see.
 */
export function AgentOverviewDetails({ item, health, period, agentHref }: AgentOverviewDetailsProps) {
  return (
    <div className="grid gap-4 p-4" style={PANEL_GRID_STYLE} data-testid="agent-overview-details">
      <Panel title="Status" href={agentHref} linkLabel="Open agent" testId="agent-overview-status">
        <StatusPanel item={item} health={health} />
      </Panel>
      <Panel
        title="Cost"
        href={`${agentHref}?tab=costs`}
        linkLabel="See costs"
        testId="agent-overview-cost"
      >
        {canAgent(item, "cost.read") ? (
          <CostPanel item={item} period={period} />
        ) : (
          <Muted>You don&apos;t have access to this agent&apos;s cost.</Muted>
        )}
      </Panel>
      <Panel
        title="Resource usage"
        href={`${agentHref}?tab=resource-usage`}
        linkLabel="See resource usage"
        testId="agent-overview-usage"
      >
        <UsagePanel item={item} />
      </Panel>
    </div>
  );
}

function Panel({
  title,
  href,
  linkLabel,
  testId,
  children,
}: {
  title: string;
  href: string;
  linkLabel: string;
  testId: string;
  children: ReactNode;
}) {
  return (
    <section className="af-card flex flex-col gap-3 p-4" data-testid={testId} aria-label={title}>
      <h3 className="m-0 text-[13px] font-semibold uppercase tracking-[0.06em]" style={{ color: "var(--ink-4)" }}>
        {title}
      </h3>
      <div className="flex-1">{children}</div>
      <Link href={href} className="text-[13px] font-medium underline-offset-2 hover:underline" style={{ color: "var(--ink-2)" }}>
        {linkLabel} →
      </Link>
    </section>
  );
}

function Muted({ children }: { children: ReactNode }) {
  return (
    <p className="m-0 text-[13px] leading-relaxed" style={{ color: "var(--ink-3)" }}>
      {children}
    </p>
  );
}

function Fact({ label, value, mono }: { label: string; value: ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3 text-[13px]">
      <span style={{ color: "var(--ink-4)" }}>{label}</span>
      <span className={`truncate text-right ${mono ? "font-mono" : ""}`} style={{ color: "var(--ink-2)" }}>
        {value}
      </span>
    </div>
  );
}

function StatusPanel({ item, health }: { item: AgentOverviewItem; health: AgentHealth | null }) {
  const canReadActivity = canAgent(item, "activity.read");
  const hasContainer = item.status !== "STOPPED";
  // The classified failure lives on the Agent itself. An empty id leaves the query off,
  // so a healthy row makes no extra request.
  const { agent } = useAgent(item.status === "ERROR" ? item.id : "");
  const diagnostics = useAgentRuntimeDiagnostics(canReadActivity && hasContainer ? item.id : "").data;
  const restarts = diagnostics?.available ? diagnostics.restartCount : 0;

  return (
    <div className="flex flex-col gap-2">
      <div className="mb-1">
        {item.status === "RUNNING" && !canReadActivity ? (
          <span className="text-[12.5px]" style={{ color: "var(--ink-3)" }}>
            Running
          </span>
        ) : (
          <StatusLine status={item.status} health={health} />
        )}
      </div>
      {agent?.lastError && (
        <p className="m-0 text-[13px] leading-relaxed" style={{ color: "var(--err)" }}>
          {agent.lastError.summary}
        </p>
      )}
      <Fact label="Model" value={formatModelName(item.effectiveModel) || "—"} mono />
      <Fact label="Runtime" value={item.agentType} />
      <Fact label="Created" value={new Date(item.createdAt).toLocaleDateString()} />
      {diagnostics?.available && (
        <>
          <Fact label="Restarts" value={restarts} />
          {diagnostics.terminationReason && (
            <Fact label="Last stopped by" value={diagnostics.terminationReason} />
          )}
        </>
      )}
    </div>
  );
}

function CostPanel({ item, period }: { item: AgentOverviewItem; period: OverviewPeriod }) {
  // The same period the row was totalled over, so the figure here is the row's figure.
  const filters = useMemo(() => ({ sort: "newest_first" as const, period }), [period]);
  const { agentCost, isLoadingAgentCost, error } = useAgentCost(item.id, filters);

  if (isLoadingAgentCost) return <PanelSkeleton />;
  if (error || !agentCost) return <Muted>Cost couldn&apos;t be loaded.</Muted>;
  if (agentCost.totalCalls === 0) return <Muted>No model calls in this period.</Muted>;

  return (
    <div className="flex flex-col gap-2">
      <p className="m-0 text-[22px] font-semibold" style={{ color: "var(--ink)" }}>
        {formatSpend(agentCost.totalCost)}
      </p>
      <Fact label="Calls" value={agentCost.totalCalls.toLocaleString()} />
      <Fact label="Per call" value={formatCallSpend(agentCost.avgCostPerCall)} />
      <Fact label="Per day" value={formatSpend(agentCost.dailyBurnRate)} />
      {agentCost.failedCalls > 0 && <Fact label="Failed calls" value={agentCost.failedCalls.toLocaleString()} />}
    </div>
  );
}

function UsagePanel({ item }: { item: AgentOverviewItem }) {
  const canRead = canAgent(item, "activity.read");
  const stopped = item.status === "STOPPED";
  // Only asked for what can be answered: a stopped Agent has no container, and a reader
  // without activity.read would be refused.
  const { usage, isLoadingUsage, error } = useAgentResourceUsage(item.id, "24h", canRead && !stopped);

  if (!canRead) return <Muted>You don&apos;t have access to this agent&apos;s resource usage.</Muted>;
  if (stopped) return <Muted>Stopped. Usage is recorded while the agent runs.</Muted>;
  if (isLoadingUsage) return <PanelSkeleton />;
  if (error || !usage) return <Muted>Resource usage couldn&apos;t be loaded.</Muted>;

  const notice = noticeFor(usage.availability, usage.state);
  if (notice) {
    return (
      <div className="flex flex-col gap-1">
        <p className="m-0 text-[13px] font-medium" style={{ color: "var(--ink-2)" }}>
          {notice.title}
        </p>
        <Muted>{notice.body}</Muted>
      </div>
    );
  }

  const memoryRatio = usageRatio(usage.memoryWorkingSetBytes, usage.memoryLimitBytes);
  const cpuRatio = usageRatio(usage.cpuCores, usage.cpuLimitCores);
  const throttled = usage.cpuThrottledRatio;

  return (
    <div className="flex flex-col gap-3">
      <MeterFact
        label="Memory"
        text={
          usage.memoryWorkingSetBytes !== null
            ? `${formatBytes(usage.memoryWorkingSetBytes)}${
                usage.memoryLimitBytes !== null ? ` of ${formatBytes(usage.memoryLimitBytes)}` : ""
              }`
            : "—"
        }
        ratio={memoryRatio}
      />
      <MeterFact
        label="CPU"
        text={
          usage.cpuCores !== null
            ? `${formatCores(usage.cpuCores)}${
                usage.cpuLimitCores !== null ? ` of ${formatCores(usage.cpuLimitCores)}` : ""
              } cores`
            : "—"
        }
        ratio={cpuRatio}
      />
      <div>
        <Fact label="Peak memory, 24h" value={usage.memoryPeakBytes !== null ? formatBytes(usage.memoryPeakBytes) : "—"} />
        <Fact
          label="CPU throttled, 24h"
          value={
            <span style={{ color: throttled !== null && throttled >= THROTTLING_WARN_RATIO ? "var(--warn)" : undefined }}>
              {throttled !== null ? formatPercent(throttled) : "—"}
            </span>
          }
        />
      </div>
      <MemoryChart series={usage.series} range={usage.range} limitBytes={usage.memoryLimitBytes} compact />
    </div>
  );
}

function MeterFact({ label, text, ratio }: { label: string; text: string; ratio: number | null }) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between gap-3 text-[13px]">
        <span style={{ color: "var(--ink-4)" }}>{label}</span>
        <span style={{ color: "var(--ink-2)" }}>{text}</span>
      </div>
      <UsageMeter ratio={ratio} label={`${label} use against its limit`} />
    </div>
  );
}

function PanelSkeleton() {
  return (
    <div className="flex flex-col gap-2" data-testid="agent-overview-panel-skeleton">
      <Skeleton className="h-6 w-24" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-4/5" />
    </div>
  );
}
