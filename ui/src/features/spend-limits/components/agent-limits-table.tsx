"use client";

import Link from "next/link";
import { ChevronRight, Loader2 } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { formatUsage, formatUsd } from "@/features/organizations/spend-limit";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";

import { type AgentLlmBudgetRow, useAgentLlmBudgets } from "../hooks/use-agent-llm-budgets";

const SOURCE: Record<AgentLlmBudgetRow["source"], string> = {
  agent: "Own limit",
  default: "Default",
  organization: "Held to organization limit",
};

/** Every Agent's limit in force and where it comes from — the answer to "who is not
 *  on the default?" without opening each Agent. */
/** Closest to being cut off first: at its limit, then by share of the limit spent. An
 *  Agent with no spend observed yet sorts last, since nothing is known about it. */
function byUrgency(a: AgentLlmBudgetRow, b: AgentLlmBudgetRow) {
  const share = (row: AgentLlmBudgetRow) =>
    row.spendUsd == null ? -1 : row.limitUsd > 0 ? row.spendUsd / row.limitUsd : Number.POSITIVE_INFINITY;
  return share(b) - share(a) || a.agentName.localeCompare(b.agentName);
}

export function AgentLimitsTable({ period, per }: { period: string; per: string }) {
  const { agents, isLoading, error, refetch } = useAgentLlmBudgets();
  const { selectedOrganization } = useOrganizationContext();

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
        <Loader2 size={15} className="animate-spin" /> Loading Agent limits…
      </div>
    );
  }
  if (error || !agents) {
    return <AppErrorState error={error} title="We couldn't load Agent limits" onRetry={() => void refetch()} />;
  }
  if (agents.length === 0) {
    return (
      <p className="m-0 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
        No Agents yet. New Agents start on the default Agent limit.
      </p>
    );
  }

  const rows = [...agents].sort(byUrgency);

  return (
    <div className="af-card overflow-x-auto">
      <table className="w-full text-left text-[0.86rem]" style={{ color: "var(--ink-2)" }}>
        <caption className="sr-only">
          Each Agent&apos;s model spend limit, where it comes from, and what it has spent {period}. Agents
          closest to their limit are listed first.
        </caption>
        <thead>
          <tr style={{ color: "var(--ink-4)" }}>
            <th scope="col" className="px-4 py-2.5 text-[0.72rem] font-semibold uppercase tracking-[0.08em]">
              Agent
            </th>
            <th scope="col" className="px-4 py-2.5 text-[0.72rem] font-semibold uppercase tracking-[0.08em]">
              Limit
            </th>
            <th scope="col" className="px-4 py-2.5 text-[0.72rem] font-semibold uppercase tracking-[0.08em]">
              Set by
            </th>
            <th scope="col" className="px-4 py-2.5 text-[0.72rem] font-semibold uppercase tracking-[0.08em]">
              Spent {period}
            </th>
            <th scope="col" className="px-4 py-2.5">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((agent) => (
            <tr key={agent.agentId} style={{ borderTop: "1px solid var(--line)" }}>
              <th scope="row" className="px-4 py-2.5 font-medium" style={{ color: "var(--ink)" }}>
                {agent.agentName}
              </th>
              <td className="px-4 py-2.5 tabular-nums">
                {formatUsd(agent.limitUsd)} <span style={{ color: "var(--ink-3)" }}>{per}</span>
              </td>
              <td className="px-4 py-2.5">{SOURCE[agent.source]}</td>
              <td
                className="px-4 py-2.5"
                style={{ color: agent.state === "exhausted" ? "var(--err)" : undefined }}
              >
                {agent.spendUsd == null
                  ? "Not available yet"
                  : `${formatUsage(agent.spendUsd, agent.limitUsd)}${agent.state === "exhausted" ? " — limit reached" : ""}`}
              </td>
              <td className="px-4 py-2.5 text-right">
                <Link
                  href={`/dashboard/${selectedOrganization?.id}/agents/${agent.agentId}/configuration?section=spend`}
                  className="inline-flex min-h-11 items-center gap-1 font-medium underline-offset-2 hover:underline"
                  style={{ color: "var(--ink)" }}
                  aria-label={`Change ${agent.agentName}'s limit`}
                >
                  Change <ChevronRight size={14} aria-hidden />
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
