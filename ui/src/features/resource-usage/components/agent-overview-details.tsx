"use client";

import { useMemo } from "react";

import { useAgent } from "@/features/agents/hooks/use-agent";
import { useAgentRuntimeDiagnostics } from "@/features/agents/hooks/use-agent-runtime-diagnostics";
import type { AgentHealth } from "@/features/agents/schemas";
import { canAgent } from "@/features/agents/utils";
import { useAgentCost } from "@/features/costs/hooks/use-agent-cost";
import { formatCallSpend, formatSpend } from "@/features/costs/format";

import { useAgentResourceUsage } from "../hooks/use-agent-resource-usage";
import type { AgentOverviewItem } from "../schemas";
import type { OverviewPeriod } from "../utils";
import { Fact, Muted, PANEL_GRID_STYLE, Panel, PanelSkeleton, StatusFacts, UsageFacts } from "./agent-detail-panels";

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

function StatusPanel({ item, health }: { item: AgentOverviewItem; health: AgentHealth | null }) {
  const canReadActivity = canAgent(item, "activity.read");
  const hasContainer = item.status !== "STOPPED";
  // The classified failure lives on the Agent itself. An empty id leaves the query off,
  // so a healthy row makes no extra request.
  const { agent } = useAgent(item.status === "ERROR" ? item.id : "");
  const diagnostics = useAgentRuntimeDiagnostics(canReadActivity && hasContainer ? item.id : "").data;

  return (
    <StatusFacts
      status={item.status}
      health={health}
      canReadHealth={canReadActivity}
      lastErrorSummary={agent?.lastError?.summary ?? null}
      effectiveModel={item.effectiveModel}
      agentType={item.agentType}
      createdAt={item.createdAt}
      restartCount={diagnostics?.available ? diagnostics.restartCount : null}
      terminationReason={diagnostics?.available ? (diagnostics.terminationReason ?? null) : null}
    />
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

  return <UsageFacts canRead={canRead} stopped={stopped} isLoading={isLoadingUsage} failed={!!error} usage={usage} />;
}
