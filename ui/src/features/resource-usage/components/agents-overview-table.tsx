"use client";

import Link from "next/link";
import { Fragment, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, ChevronUp, TriangleAlert } from "lucide-react";

import { AgentAvatar } from "@/features/agents/components/agent-avatar";
import { StatusLine } from "@/features/agents/components/status-line";
import { useAgentHealth } from "@/features/agents/hooks/use-agent-health";
import { canAgent, formatModelName } from "@/features/agents/utils";
import { formatPercent, formatSpend } from "@/features/costs/format";

import { formatBytes, formatCores } from "../format";
import type { AgentOverviewItem, AgentUsageSnapshot } from "../schemas";
import {
  OVERVIEW_HEALTH_REFETCH_MS,
  THROTTLING_WARN_RATIO,
  usageRatio,
  type OverviewPeriod,
} from "../utils";
import { AgentOverviewDetails } from "./agent-overview-details";
import { UsageMeter } from "./usage-meter";

type SortKey = "name" | "spend" | "cpu" | "memory";
type SortDirection = "asc" | "desc";

const COLUMNS: { key: SortKey; label: string; numeric: boolean }[] = [
  { key: "name", label: "Agent", numeric: false },
  { key: "spend", label: "Spend", numeric: true },
  { key: "cpu", label: "CPU", numeric: false },
  { key: "memory", label: "Memory", numeric: false },
];

const COLUMN_COUNT = COLUMNS.length + 1;

const STATE_HINT: Record<AgentUsageSnapshot["state"], string> = {
  reporting: "",
  restart_required: "Restart to report",
  unsupported: "Not supported",
  no_data: "No data yet",
};

/** What a column sorts by. Usage sorts by share of its limit when there is one, since
 *  "using 90% of its memory" is the comparison that matters, and by the raw amount
 *  otherwise. Null means "nothing to compare", which always sorts last. */
function sortValue(item: AgentOverviewItem, key: SortKey): string | number | null {
  switch (key) {
    case "name":
      return item.name.toLowerCase();
    case "spend":
      return item.spend?.spend ?? null;
    case "cpu": {
      const usage = item.resourceUsage;
      if (!usage || usage.state !== "reporting") return null;
      return usageRatio(usage.cpuCores, usage.cpuLimitCores) ?? usage.cpuCores;
    }
    case "memory": {
      const usage = item.resourceUsage;
      if (!usage || usage.state !== "reporting") return null;
      return usageRatio(usage.memoryWorkingSetBytes, usage.memoryLimitBytes) ?? usage.memoryWorkingSetBytes;
    }
  }
}

function compareItems(a: AgentOverviewItem, b: AgentOverviewItem, key: SortKey, direction: SortDirection) {
  const left = sortValue(a, key);
  const right = sortValue(b, key);
  if (left === right) return 0;
  // Nothing to compare goes last in either direction, so a sort never buries the
  // Agents that have numbers under the ones that do not.
  if (left === null) return 1;
  if (right === null) return -1;
  const order = left < right ? -1 : 1;
  return direction === "asc" ? order : -order;
}

interface AgentsOverviewTableProps {
  items: AgentOverviewItem[];
  period: OverviewPeriod;
  orgId: string;
}

/**
 * Agents with the headline figures in the row and the detail one click away.
 *
 * Spend is the second column and the largest text in the row: it is the figure the page
 * exists to put in front of an evaluator. Sorting is client-side, since the page holds
 * every row it will ever show.
 */
export function AgentsOverviewTable({ items, period, orgId }: AgentsOverviewTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>("spend");
  const [direction, setDirection] = useState<SortDirection>("desc");
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());

  const sorted = useMemo(
    () => [...items].sort((a, b) => compareItems(a, b, sortKey, direction)),
    [items, sortKey, direction],
  );

  const toggleSort = (key: SortKey) => {
    if (key === sortKey) {
      setDirection((current) => (current === "asc" ? "desc" : "asc"));
      return;
    }
    setSortKey(key);
    // Names read best A-Z; every figure is most useful biggest-first.
    setDirection(key === "name" ? "asc" : "desc");
  };

  const toggleExpanded = (id: string) => {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div className="af-card overflow-x-auto" style={{ padding: 0 }} data-testid="agents-overview-table">
      <table className="w-full border-collapse text-[13px]">
        <thead>
          <tr style={{ borderBottom: "1px solid var(--line)" }}>
            <th style={{ width: "2.5rem" }}>
              <span className="sr-only">Details</span>
            </th>
            {COLUMNS.map(({ key, label, numeric }) => {
              const active = key === sortKey;
              return (
                <th
                  key={key}
                  scope="col"
                  className={`px-3 py-3 font-medium ${numeric ? "text-right" : "text-left"}`}
                  aria-sort={active ? (direction === "asc" ? "ascending" : "descending") : "none"}
                >
                  <button
                    type="button"
                    className={`af-hover-bg inline-flex items-center gap-1 rounded px-1.5 py-1 ${
                      numeric ? "flex-row-reverse" : ""
                    }`}
                    style={{ color: active ? "var(--ink)" : "var(--ink-3)" }}
                    onClick={() => toggleSort(key)}
                    data-testid={`agents-overview-sort-${key}`}
                  >
                    {label}
                    {active &&
                      (direction === "asc" ? <ChevronUp size={13} /> : <ChevronDown size={13} />)}
                  </button>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.map((item, index) => (
            <AgentRow
              key={item.id}
              item={item}
              first={index === 0}
              period={period}
              orgId={orgId}
              expanded={expanded.has(item.id)}
              onToggle={() => toggleExpanded(item.id)}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AgentRow({
  item,
  first,
  period,
  orgId,
  expanded,
  onToggle,
}: {
  item: AgentOverviewItem;
  first: boolean;
  period: OverviewPeriod;
  orgId: string;
  expanded: boolean;
  onToggle: () => void;
}) {
  const canReadActivity = canAgent(item, "activity.read");
  // Health needs activity.read and a running Agent; without either the request would be
  // refused, so it is not made and the row does not claim to know.
  const { health } = useAgentHealth(
    item.id,
    canReadActivity && item.status === "RUNNING",
    OVERVIEW_HEALTH_REFETCH_MS,
  );
  const agentHref = `/dashboard/${orgId}/agents/${item.id}`;
  const detailsId = `agent-overview-details-${item.id}`;

  return (
    <Fragment>
      <tr
        className="af-hover-bg cursor-pointer"
        style={{ borderTop: first ? undefined : "1px solid var(--line)" }}
        onClick={onToggle}
        data-testid="agents-overview-row"
        data-agent-name={item.name}
      >
        <td className="px-2 py-3 align-middle">
          <button
            type="button"
            className="af-hover-bg grid h-7 w-7 place-items-center rounded"
            style={{ color: "var(--ink-3)" }}
            aria-expanded={expanded}
            aria-controls={detailsId}
            aria-label={`${expanded ? "Hide" : "Show"} details for ${item.name}`}
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
        </td>
        <td className="px-3 py-3 align-middle">
          <div className="flex min-w-0 items-center gap-3">
            <AgentAvatar agent={item} size="sm" />
            <div className="min-w-0">
              <Link
                href={agentHref}
                className="block truncate text-[14px] font-medium hover:underline"
                style={{ color: "var(--ink)" }}
                onClick={(event) => event.stopPropagation()}
              >
                {item.name}
              </Link>
              <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                <RowStatus item={item} health={health} canReadActivity={canReadActivity} />
                {item.effectiveModel && (
                  // The model is the first thing to go on a narrow screen, so Spend stays in view.
                  <span className="hidden truncate font-mono text-[11.5px] sm:inline" style={{ color: "var(--ink-4)" }}>
                    {formatModelName(item.effectiveModel)}
                  </span>
                )}
              </div>
            </div>
          </div>
        </td>
        <td className="px-3 py-3 text-right align-middle">
          <SpendCell item={item} />
        </td>
        <td className="px-3 py-3 align-middle">
          <CpuCell item={item} />
        </td>
        <td className="px-3 py-3 align-middle">
          <MemoryCell item={item} />
        </td>
      </tr>
      {expanded && (
        <tr id={detailsId} style={{ borderTop: "1px solid var(--line)", background: "var(--bg-soft)" }}>
          <td colSpan={COLUMN_COUNT}>
            <AgentOverviewDetails item={item} health={health} period={period} agentHref={agentHref} />
          </td>
        </tr>
      )}
    </Fragment>
  );
}

function RowStatus({
  item,
  health,
  canReadActivity,
}: {
  item: AgentOverviewItem;
  health: ReturnType<typeof useAgentHealth>["health"];
  canReadActivity: boolean;
}) {
  // A running Agent whose health cannot be read is only known to be running.
  if (item.status === "RUNNING" && !canReadActivity) {
    return (
      <span className="text-[12.5px]" style={{ color: "var(--ink-3)" }}>
        Running
      </span>
    );
  }
  return <StatusLine status={item.status} health={health} />;
}

function Unavailable({ reason }: { reason: string }) {
  return (
    <span title={reason} style={{ color: "var(--ink-4)" }}>
      —
    </span>
  );
}

function SpendCell({ item }: { item: AgentOverviewItem }) {
  if (!item.spend) return <Unavailable reason="You don't have access to this agent's cost" />;
  return (
    <div data-testid="agents-overview-spend">
      <div className="text-[16px] font-semibold tabular-nums" style={{ color: "var(--ink)" }}>
        {formatSpend(item.spend.spend)}
      </div>
      <div className="text-[11.5px] tabular-nums" style={{ color: "var(--ink-4)" }}>
        {item.spend.calls.toLocaleString()} {item.spend.calls === 1 ? "call" : "calls"}
      </div>
    </div>
  );
}

function usageOrReason(item: AgentOverviewItem): AgentUsageSnapshot | { reason: string } {
  if (item.resourceUsage) return item.resourceUsage;
  if (!canAgent(item, "activity.read")) return { reason: "You don't have access to this agent's resource usage" };
  if (item.status === "STOPPED") return { reason: "Stopped" };
  return { reason: "Resource usage isn't available right now" };
}

function CpuCell({ item }: { item: AgentOverviewItem }) {
  const usage = usageOrReason(item);
  if ("reason" in usage) return <Unavailable reason={usage.reason} />;
  if (usage.state !== "reporting") return <StateHint state={usage.state} />;

  const throttled = usage.cpuThrottledRatio;
  return (
    <div className="min-w-[8rem]" data-testid="agents-overview-cpu">
      <div className="flex items-center gap-1.5 tabular-nums" style={{ color: "var(--ink-2)" }}>
        {usage.cpuCores !== null
          ? `${formatCores(usage.cpuCores)}${usage.cpuLimitCores !== null ? ` / ${formatCores(usage.cpuLimitCores)}` : ""} cores`
          : "—"}
        {throttled !== null && throttled >= THROTTLING_WARN_RATIO && (
          <span
            title={`Held back at its CPU limit ${formatPercent(throttled)} of the last hour`}
            aria-label={`Throttled ${formatPercent(throttled)} of the last hour`}
            data-testid="agents-overview-throttled"
            style={{ color: "var(--warn)" }}
          >
            <TriangleAlert size={14} />
          </span>
        )}
      </div>
      <UsageMeter ratio={usageRatio(usage.cpuCores, usage.cpuLimitCores)} label="CPU use against its limit" className="mt-1.5" />
    </div>
  );
}

function MemoryCell({ item }: { item: AgentOverviewItem }) {
  const usage = usageOrReason(item);
  if ("reason" in usage) return <Unavailable reason={usage.reason} />;
  if (usage.state !== "reporting") return <StateHint state={usage.state} />;

  return (
    <div className="min-w-[8rem]" data-testid="agents-overview-memory">
      <div className="tabular-nums" style={{ color: "var(--ink-2)" }}>
        {usage.memoryWorkingSetBytes !== null
          ? `${formatBytes(usage.memoryWorkingSetBytes)}${usage.memoryLimitBytes !== null ? ` / ${formatBytes(usage.memoryLimitBytes)}` : ""}`
          : "—"}
      </div>
      <UsageMeter
        ratio={usageRatio(usage.memoryWorkingSetBytes, usage.memoryLimitBytes)}
        label="Memory use against its limit"
        className="mt-1.5"
      />
    </div>
  );
}

function StateHint({ state }: { state: AgentUsageSnapshot["state"] }) {
  return (
    <span className="text-[12px]" style={{ color: "var(--ink-4)" }} data-state={state}>
      {STATE_HINT[state]}
    </span>
  );
}
