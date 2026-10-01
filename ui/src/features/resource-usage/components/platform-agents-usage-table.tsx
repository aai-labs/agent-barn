"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { ChevronDown } from "lucide-react";

import { formatPercent } from "@/features/costs/format";

import { formatBytes, formatCores } from "../format";
import type { PlatformAgentUsage } from "../schemas";
import { THROTTLING_WARN_RATIO, usageRatio } from "../utils";
import { UsageMeter } from "./usage-meter";

type SortKey = "memory" | "cpu";

const TOP_COUNT = 10;

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
 * Platform page.
 */
export function PlatformAgentsUsageTable({ agents }: { agents: PlatformAgentUsage[] }) {
  const [sortKey, setSortKey] = useState<SortKey>("memory");
  const [showAll, setShowAll] = useState(false);

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
        No agent is reporting CPU or memory right now.
      </div>
    );
  }

  return (
    <div className="af-card overflow-x-auto" style={{ padding: 0 }} data-testid="platform-agents-usage">
      <table className="w-full min-w-[40rem] border-collapse text-[13px]">
        <thead>
          <tr style={{ borderBottom: "1px solid var(--line)" }}>
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
          {visible.map((agent) => {
            const memoryRatio = usageRatio(agent.memoryWorkingSetBytes, agent.memoryLimitBytes);
            const cpuRatio = usageRatio(agent.cpuCores, agent.cpuLimitCores);
            const throttled = agent.cpuThrottledRatio;
            const isUnknown = agent.agentName === null;
            return (
              <tr
                key={agent.agentId}
                style={{ borderBottom: "1px solid var(--line)" }}
                data-testid="platform-agent-usage-row"
                data-agent-id={agent.agentId}
              >
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
                    <UsageMeter ratio={memoryRatio} label={`${agentLabel(agent)} memory`} className="mt-1" />
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
                    <UsageMeter ratio={cpuRatio} label={`${agentLabel(agent)} CPU`} className="mt-1" />
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
            );
          })}
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
