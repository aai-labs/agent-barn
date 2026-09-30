"use client";

import { useMemo, useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";

import { formatSpend, formatTokens } from "../format";
import type { AgentSpend } from "../schemas";

type SortKey = "agentName" | "spend" | "calls" | "tokens";
type SortDirection = "asc" | "desc";

const COLUMNS: { key: SortKey; label: string; numeric: boolean }[] = [
  { key: "agentName", label: "Agent", numeric: false },
  { key: "spend", label: "Spend", numeric: true },
  { key: "calls", label: "Calls", numeric: true },
  { key: "tokens", label: "Tokens", numeric: true },
];

const tokensOf = (agent: AgentSpend) => agent.promptTokens + agent.completionTokens;

function valueFor(agent: AgentSpend, key: SortKey): string | number {
  switch (key) {
    case "agentName":
      // Unattributed sorts as its display name rather than sinking to the bottom on
      // every sort: it is a real row and hiding it would break the total.
      return (agent.agentName ?? "Unattributed").toLowerCase();
    case "spend":
      return agent.spend;
    case "calls":
      return agent.calls;
    case "tokens":
      return tokensOf(agent);
  }
}

/**
 * Agents ranked by spend, sortable by any column.
 *
 * Sorting is client-side: the endpoint returns every agent in the window rather than
 * a page, so re-sorting is a reorder of data already held, not a refetch.
 */
export function AgentsBySpend({
  agents,
  isLoading,
  onSelectAgent,
  selectedAgentId,
}: {
  agents: AgentSpend[];
  isLoading: boolean;
  onSelectAgent: (agentId: string | null) => void;
  selectedAgentId?: string;
}) {
  const [sortKey, setSortKey] = useState<SortKey>("spend");
  const [direction, setDirection] = useState<SortDirection>("desc");

  const sorted = useMemo(() => {
    const rows = [...agents];
    rows.sort((a, b) => {
      const left = valueFor(a, sortKey);
      const right = valueFor(b, sortKey);
      if (left === right) return 0;
      const order = left < right ? -1 : 1;
      return direction === "asc" ? order : -order;
    });
    return rows;
  }, [agents, sortKey, direction]);

  const toggle = (key: SortKey) => {
    if (key === sortKey) {
      setDirection((d) => (d === "asc" ? "desc" : "asc"));
      return;
    }
    setSortKey(key);
    // Numbers are most useful biggest-first; names read best A-Z.
    setDirection(key === "agentName" ? "asc" : "desc");
  };

  if (isLoading) {
    return (
      <div className="af-card mb-6 p-4" data-testid="agents-by-spend-skeleton">
        <Skeleton className="mb-4 h-4 w-32" />
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="mb-2 h-8 w-full" />
        ))}
      </div>
    );
  }

  if (agents.length === 0) return null;

  return (
    <div className="af-card mb-6 p-4" data-testid="agents-by-spend">
      <h2
        className="m-0 mb-1 text-[14px] font-semibold"
        style={{ color: "var(--ink)" }}
      >
        Agents by spend
      </h2>
      <p className="m-0 mb-3 text-[12px]" style={{ color: "var(--ink-4)" }}>
        Every agent with spend in this period. Select one to filter the page.
      </p>

      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-[13px]">
          <thead>
            <tr>
              {COLUMNS.map(({ key, label, numeric }) => {
                const active = key === sortKey;
                return (
                  <th
                    key={key}
                    scope="col"
                    className={`py-2 font-medium ${numeric ? "text-right" : "text-left"}`}
                    style={{ borderBottom: "1px solid var(--line)" }}
                    aria-sort={
                      active
                        ? direction === "asc"
                          ? "ascending"
                          : "descending"
                        : "none"
                    }
                  >
                    <button
                      type="button"
                      className={`af-hover-bg inline-flex items-center gap-1 rounded px-1.5 py-1 ${
                        numeric ? "flex-row-reverse" : ""
                      }`}
                      style={{ color: active ? "var(--ink)" : "var(--ink-3)" }}
                      onClick={() => toggle(key)}
                    >
                      {label}
                      {active &&
                        (direction === "asc" ? (
                          <ChevronUp size={13} />
                        ) : (
                          <ChevronDown size={13} />
                        ))}
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {sorted.map((agent) => {
              const id = agent.agentId;
              const isSelected = !!id && id === selectedAgentId;
              return (
                <tr
                  key={id ?? "unattributed"}
                  className={id ? "af-hover-bg cursor-pointer" : undefined}
                  style={{
                    background: isSelected ? "var(--bg-soft)" : "transparent",
                  }}
                  onClick={() => id && onSelectAgent(isSelected ? null : id)}
                >
                  <td className="py-2" style={{ color: "var(--ink-2)" }}>
                    {agent.agentName ?? "Unattributed"}
                  </td>
                  <td
                    className="py-2 text-right tabular-nums"
                    style={{ color: "var(--ink)" }}
                  >
                    {formatSpend(agent.spend)}
                  </td>
                  <td
                    className="py-2 text-right tabular-nums"
                    style={{ color: "var(--ink-3)" }}
                  >
                    {agent.calls.toLocaleString()}
                  </td>
                  <td
                    className="py-2 text-right tabular-nums"
                    style={{ color: "var(--ink-3)" }}
                  >
                    {formatTokens(tokensOf(agent))}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
