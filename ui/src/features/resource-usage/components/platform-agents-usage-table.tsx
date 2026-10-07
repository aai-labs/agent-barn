"use client";

import Link from "next/link";
import { Fragment, useMemo, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import { formatPercent } from "@/features/costs/format";

import { formatBytes, formatCores } from "../format";
import type { PlatformAgentUsage } from "../schemas";
import { THROTTLING_WARN_RATIO, usageRatio } from "../utils";
import { PlatformAgentDetails } from "./platform-agent-details";
import { UsageMeter } from "./usage-meter";

type SortKey = "memory" | "cpu";

const TOP_COUNT = 10;

// The chevron, Agent, Organization, Memory, CPU and CPU throttled.
const COLUMN_COUNT = 6;

/** What a container with no live agent is called: enough of its id to find its Deployment. */
export function agentLabel(agent: PlatformAgentUsage): string {
  return agent.agentName ?? `agent-${agent.agentId.slice(0, 8)}`;
}

function amount(agent: PlatformAgentUsage, key: SortKey): number {
  return (key === "memory" ? agent.memoryWorkingSetBytes : agent.cpuCores) ?? 0;
}

/**
 * The heaviest containers first, ten at a time.
 *
 * Names are plain text, not links: a Platform Administrator has no Membership, so an
 * Organization's agent page is not one they can open. The Organization links to its
 * Platform page. A row opens to the same Status and Resource usage panels the
 * Organization Usage page shows, without the Cost panel and without links.
 */
export function PlatformAgentsUsageTable({
  agents,
  needUpdate,
}: {
  agents: PlatformAgentUsage[];
  /** Agents that cannot report until they are updated, for the empty state to say so. */
  needUpdate: number;
}) {
  const [sortKey, setSortKey] = useState<SortKey>("memory");
  const [showAll, setShowAll] = useState(false);
  // Kept here, by Agent id, so a row stays open when the table is sorted or trimmed.
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());

  const toggleExpanded = (agentId: string) => {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(agentId)) next.delete(agentId);
      else next.add(agentId);
      return next;
    });
  };

  const sorted = useMemo(
    () => [...agents].sort((a, b) => amount(b, sortKey) - amount(a, sortKey)),
    [agents, sortKey],
  );
  const visible = showAll ? sorted : sorted.slice(0, TOP_COUNT);

  if (agents.length === 0) {
    return (
      <div
        className="rounded-2xl px-5 py-10 text-center text-[0.844rem]"
        style={{ border: "1px dashed var(--line-strong)", color: "var(--ink-3)" }}
        data-testid="platform-agents-empty"
      >
        <p className="m-0">No agent is reporting CPU or memory right now.</p>
        {needUpdate > 0 && (
          <p className="m-0 mt-1.5" data-testid="platform-agents-need-update">
            {needUpdate === 1 ? "1 agent is" : `${needUpdate} agents are`} running an older version. Their owners can
            update them from the agent page to start reporting.
          </p>
        )}
      </div>
    );
  }

  return (
    // A container, so an opened row can be as wide as what is visible (100cqw) rather than
    // as wide as the table, which scrolls sideways below its minimum width.
    <div className="af-card overflow-x-auto @container" style={{ padding: 0 }} data-testid="platform-agents-usage">
      <table className="w-full min-w-[44rem] border-collapse text-[13px]">
        <thead>
          <tr style={{ borderBottom: "1px solid var(--line)" }}>
            <th style={{ width: "2.5rem" }}>
              <span className="sr-only">Details</span>
            </th>
            <th scope="col" className="px-3 py-3 text-left font-medium">
              Agent
            </th>
            <th scope="col" className="px-3 py-3 text-left font-medium">
              Organization
            </th>
            {(["memory", "cpu"] as const).map((key) => (
              <th
                key={key}
                scope="col"
                className="px-3 py-3 text-left font-medium"
                aria-sort={sortKey === key ? "descending" : "none"}
              >
                <button
                  type="button"
                  className="af-hover-bg inline-flex items-center gap-1 rounded px-1.5 py-1"
                  onClick={() => setSortKey(key)}
                  data-testid={`platform-agents-sort-${key}`}
                >
                  {key === "memory" ? "Memory" : "CPU"}
                  {sortKey === key && <ChevronDown size={13} aria-hidden="true" />}
                </button>
              </th>
            ))}
            <th scope="col" className="px-3 py-3 text-right font-medium">
              CPU throttled
            </th>
          </tr>
        </thead>
        <tbody>
          {visible.map((agent) => (
            <AgentRow
              key={agent.agentId}
              agent={agent}
              expanded={expanded.has(agent.agentId)}
              onToggle={() => toggleExpanded(agent.agentId)}
            />
          ))}
        </tbody>
      </table>
      {agents.length > TOP_COUNT && (
        <div className="px-3 py-2.5" style={{ borderTop: "1px solid var(--line)" }}>
          <button
            type="button"
            className="af-btn af-btn-sm"
            onClick={() => setShowAll((current) => !current)}
            data-testid="platform-agents-show-all"
          >
            {showAll ? `Show the top ${TOP_COUNT}` : `Show all ${agents.length}`}
          </button>
        </div>
      )}
    </div>
  );
}

function AgentRow({
  agent,
  expanded,
  onToggle,
}: {
  agent: PlatformAgentUsage;
  expanded: boolean;
  onToggle: () => void;
}) {
  const memoryRatio = usageRatio(agent.memoryWorkingSetBytes, agent.memoryLimitBytes);
  const cpuRatio = usageRatio(agent.cpuCores, agent.cpuLimitCores);
  const throttled = agent.cpuThrottledRatio;
  const isUnknown = agent.agentName === null;
  // A container with no live agent has no record to show a status for, and its figures are
  // already in the row, so there is nothing to open.
  const canExpand = !isUnknown;
  const detailsId = `platform-agent-details-${agent.agentId}`;

  return (
    <Fragment>
      <tr
        className={canExpand ? "af-hover-bg cursor-pointer" : undefined}
        style={{ borderBottom: "1px solid var(--line)" }}
        onClick={canExpand ? onToggle : undefined}
        data-testid="platform-agent-usage-row"
        data-agent-id={agent.agentId}
      >
        <td className="px-2 py-2.5 align-middle">
          {canExpand && (
            <button
              type="button"
              className="af-hover-bg grid h-7 w-7 place-items-center rounded"
              style={{ color: "var(--ink-3)" }}
              aria-expanded={expanded}
              aria-controls={detailsId}
              aria-label={`${expanded ? "Hide" : "Show"} details for ${agentLabel(agent)}`}
              onClick={(event) => {
                // The row toggles on click too; without this the two would cancel out.
                event.stopPropagation();
                onToggle();
              }}
            >
              <ChevronRight
                size={16}
                style={{ transform: expanded ? "rotate(90deg)" : undefined, transition: "transform .15s" }}
              />
            </button>
          )}
        </td>
        <td className="px-3 py-2.5">
          <span
            className="font-medium"
            style={{ color: isUnknown ? "var(--ink-4)" : "var(--ink)" }}
            title={isUnknown ? "No live agent has this id. Its container is still running." : undefined}
          >
            {agentLabel(agent)}
          </span>
        </td>
        <td className="px-3 py-2.5" style={{ color: "var(--ink-3)" }}>
          {agent.organizationId && agent.organizationName ? (
            <Link
              href={`/dashboard/platform/organizations/${agent.organizationId}`}
              className="underline-offset-2 hover:underline"
              onClick={(event) => event.stopPropagation()}
            >
              {agent.organizationName}
            </Link>
          ) : (
            "—"
          )}
        </td>
        <td className="px-3 py-2.5">
          <div className="min-w-[8rem]">
            <span style={{ color: "var(--ink)" }}>
              {agent.memoryWorkingSetBytes !== null ? formatBytes(agent.memoryWorkingSetBytes) : "—"}
            </span>
            {agent.memoryLimitBytes !== null && (
              <span style={{ color: "var(--ink-4)" }}> / {formatBytes(agent.memoryLimitBytes)}</span>
            )}
            <UsageMeter
              ratio={memoryRatio}
              markerRatio={usageRatio(agent.memoryRequestBytes, agent.memoryLimitBytes)}
              label={`${agentLabel(agent)} memory`}
              className="mt-1"
            />
            {agent.memoryRequestBytes !== null && (
              <div className="mt-0.5 text-[0.75rem]" style={{ color: "var(--ink-4)" }} data-testid="platform-agent-memory-request">
                requests {formatBytes(agent.memoryRequestBytes)}
              </div>
            )}
          </div>
        </td>
        <td className="px-3 py-2.5">
          <div className="min-w-[8rem]">
            <span style={{ color: "var(--ink)" }}>
              {agent.cpuCores !== null ? `${formatCores(agent.cpuCores)} cores` : "—"}
            </span>
            {agent.cpuLimitCores !== null && (
              <span style={{ color: "var(--ink-4)" }}> / {formatCores(agent.cpuLimitCores)}</span>
            )}
            <UsageMeter
              ratio={cpuRatio}
              markerRatio={usageRatio(agent.cpuRequestCores, agent.cpuLimitCores)}
              label={`${agentLabel(agent)} CPU`}
              className="mt-1"
            />
            {agent.cpuRequestCores !== null && (
              <div className="mt-0.5 text-[0.75rem]" style={{ color: "var(--ink-4)" }} data-testid="platform-agent-cpu-request">
                requests {formatCores(agent.cpuRequestCores)} cores
              </div>
            )}
          </div>
        </td>
        <td
          className="px-3 py-2.5 text-right"
          style={{
            color: throttled !== null && throttled >= THROTTLING_WARN_RATIO ? "var(--warn)" : "var(--ink-3)",
          }}
        >
          {throttled !== null ? formatPercent(throttled) : "—"}
        </td>
      </tr>
      {expanded && canExpand && (
        <tr
          id={detailsId}
          style={{ borderBottom: "1px solid var(--line)", background: "var(--bg-soft)" }}
          data-testid="platform-agent-details-row"
        >
          <td colSpan={COLUMN_COUNT}>
            {/* Held at the left edge while the table scrolls, so it is read without scrolling. */}
            <div className="sticky left-0 w-[100cqw]">
              <PlatformAgentDetails agentId={agent.agentId} />
            </div>
          </td>
        </tr>
      )}
    </Fragment>
  );
}
