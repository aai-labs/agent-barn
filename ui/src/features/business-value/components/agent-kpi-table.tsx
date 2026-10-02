"use client";

import { useMemo, useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";

import { Badge } from "@/components/badge";
import { formatCallSpend, formatSpend } from "@/features/costs/format";

import {
  NOT_ENOUGH_DATA,
  formatCount,
  formatHours,
  formatRate,
  formatResponseTime,
  formatValuePerDollar,
  missingFigure,
} from "../format";
import type {
  ActivityTotals,
  OrganizationActivity,
  OrganizationValue,
} from "../schemas";
import { mergeAgentRows, type AgentKpiRow } from "../utils";
import { type KpiSource, RetryButton } from "./kpi-tiles";

const FAILED_CELL = "—";

type SortKey =
  | "agent"
  | "value"
  | "hours"
  | "spend"
  | "ratio"
  | "requests"
  | "handled"
  | "median"
  | "costPerRequest"
  | "toolCalls";
type SortDirection = "asc" | "desc";

type Cell = { text: string; sort: number | string | null };

type ValueFigures = {
  minutesSaved: number;
  value: number | null;
  spend: number;
  valueToSpendRatio: number | null;
};

type RowFigures = {
  row: AgentKpiRow;
  value: ValueFigures | null;
  activity: ActivityTotals | null;
  rateIsSet: boolean;
};

const IDLE_ACTIVITY: ActivityTotals = {
  requests: 0,
  handledWithoutFailureRate: null,
  handledCoverage: 0,
  medianResponseSeconds: null,
  responseTimeCoverage: 0,
  costPerRequest: null,
  toolCallsPerRequest: null,
};

const COLUMNS: { key: SortKey; label: string; numeric: boolean; cell: (f: RowFigures) => Cell }[] = [
  {
    key: "agent",
    label: "Agent",
    numeric: false,
    cell: ({ row }) => ({ text: row.name, sort: row.name.toLowerCase() }),
  },
  {
    key: "value",
    label: "Value",
    numeric: true,
    cell: ({ value, rateIsSet }) =>
      valueCell(value, (v) =>
        v.value === null
          ? { text: missingFigure(rateIsSet), sort: null }
          : { text: formatSpend(v.value), sort: v.value },
      ),
  },
  {
    key: "hours",
    label: "Hours saved",
    numeric: true,
    cell: ({ value }) =>
      valueCell(value, (v) => ({ text: formatHours(v.minutesSaved), sort: v.minutesSaved })),
  },
  {
    key: "spend",
    label: "LLM spend",
    numeric: true,
    cell: ({ value }) => valueCell(value, (v) => ({ text: formatSpend(v.spend), sort: v.spend })),
  },
  {
    key: "ratio",
    label: "Value per dollar",
    numeric: true,
    cell: ({ value, rateIsSet }) =>
      valueCell(value, (v) =>
        v.valueToSpendRatio === null
          ? { text: missingFigure(rateIsSet), sort: null }
          : { text: formatValuePerDollar(v.valueToSpendRatio), sort: v.valueToSpendRatio },
      ),
  },
  {
    key: "requests",
    label: "Requests",
    numeric: true,
    cell: ({ activity }) =>
      activityCell(activity, (a) => ({ text: formatCount(a.requests), sort: a.requests })),
  },
  {
    key: "handled",
    label: "Handled without failure",
    numeric: true,
    cell: ({ activity }) =>
      activityCell(activity, (a) =>
        a.handledWithoutFailureRate === null
          ? { text: NOT_ENOUGH_DATA, sort: null }
          : {
              text: `${formatRate(a.handledWithoutFailureRate)} · ${formatCount(a.handledCoverage)} reqs`,
              sort: a.handledWithoutFailureRate,
            },
      ),
  },
  {
    key: "median",
    label: "Median response",
    numeric: true,
    cell: ({ activity }) =>
      activityCell(activity, (a) =>
        a.medianResponseSeconds === null
          ? { text: NOT_ENOUGH_DATA, sort: null }
          : {
              text: `${formatResponseTime(a.medianResponseSeconds)} · ${formatCount(a.responseTimeCoverage)} reqs`,
              sort: a.medianResponseSeconds,
            },
      ),
  },
  {
    key: "costPerRequest",
    label: "Cost per request",
    numeric: true,
    cell: ({ activity }) =>
      activityCell(activity, (a) =>
        a.costPerRequest === null
          ? { text: NOT_ENOUGH_DATA, sort: null }
          : { text: formatCallSpend(a.costPerRequest), sort: a.costPerRequest },
      ),
  },
  {
    key: "toolCalls",
    label: "Tool calls per request",
    numeric: true,
    cell: ({ activity }) =>
      activityCell(activity, (a) =>
        a.toolCallsPerRequest === null
          ? { text: NOT_ENOUGH_DATA, sort: null }
          : { text: a.toolCallsPerRequest.toFixed(1), sort: a.toolCallsPerRequest },
      ),
  },
];

function valueCell(value: ValueFigures | null, render: (v: ValueFigures) => Cell): Cell {
  return value ? render(value) : { text: FAILED_CELL, sort: null };
}

function activityCell(activity: ActivityTotals | null, render: (a: ActivityTotals) => Cell): Cell {
  return activity ? render(activity) : { text: FAILED_CELL, sort: null };
}

function compareCells(left: Cell, right: Cell, direction: SortDirection): number {
  if (left.sort === null && right.sort === null) return 0;
  if (left.sort === null) return 1;
  if (right.sort === null) return -1;
  if (left.sort === right.sort) return 0;
  const order = left.sort < right.sort ? -1 : 1;
  return direction === "asc" ? order : -order;
}

export function AgentKpiTable({
  value,
  activity,
}: {
  value: KpiSource<OrganizationValue>;
  activity: KpiSource<OrganizationActivity>;
}) {
  const [sortKey, setSortKey] = useState<SortKey>("hours");
  const [direction, setDirection] = useState<SortDirection>("desc");

  const figures = useMemo(() => {
    const rateIsSet = value.data?.totals.hourlyRateUsd != null;
    const rows = mergeAgentRows(value.data?.agents ?? [], activity.data?.agents ?? []);
    return rows.map(
      (row): RowFigures => ({
        row,
        rateIsSet,
        value: value.data
          ? (row.value ?? {
              minutesSaved: 0,
              value: rateIsSet ? 0 : null,
              spend: 0,
              valueToSpendRatio: null,
            })
          : null,
        activity: activity.data ? (row.activity ?? IDLE_ACTIVITY) : null,
      }),
    );
  }, [value.data, activity.data]);

  const sorted = useMemo(() => {
    const column = COLUMNS.find((c) => c.key === sortKey)!;
    return [...figures].sort((a, b) => compareCells(column.cell(a), column.cell(b), direction));
  }, [figures, sortKey, direction]);

  const toggle = (key: SortKey) => {
    if (key === sortKey) {
      setDirection((d) => (d === "asc" ? "desc" : "asc"));
      return;
    }
    setSortKey(key);
    setDirection(key === "agent" ? "asc" : "desc");
  };

  if (figures.length === 0 && !value.error && !activity.error) return null;

  return (
    <div className="af-card mb-6 p-4" data-testid="kpi-agents">
      <h2 className="m-0 mb-1 text-[14px] font-semibold" style={{ color: "var(--ink)" }}>
        Agents
      </h2>
      <p className="m-0 mb-3 text-[12px]" style={{ color: "var(--ink-4)" }}>
        Every agent with work or spend in this period.
      </p>

      {Boolean(value.error) && <SourceError label="value figures" onRetry={value.onRetry} />}
      {Boolean(activity.error) && (
        <SourceError label="activity figures" onRetry={activity.onRetry} />
      )}

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
                      active ? (direction === "asc" ? "ascending" : "descending") : "none"
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
                        (direction === "asc" ? <ChevronUp size={13} /> : <ChevronDown size={13} />)}
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {sorted.map((rowFigures) => (
              <tr key={rowFigures.row.key}>
                {COLUMNS.map(({ key, numeric, cell }) =>
                  key === "agent" ? (
                    <td key={key} data-column={key} className="py-2" style={{ color: "var(--ink-2)" }}>
                      <span className="inline-flex items-center gap-2">
                        <span data-agent-name>{rowFigures.row.name}</span>
                        {rowFigures.row.deleted && <Badge>Deleted</Badge>}
                      </span>
                    </td>
                  ) : (
                    <td
                      key={key}
                      data-column={key}
                      className={`py-2 tabular-nums whitespace-nowrap ${numeric ? "text-right" : ""}`}
                      style={{ color: "var(--ink-3)" }}
                    >
                      {cell(rowFigures).text}
                    </td>
                  ),
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SourceError({ label, onRetry }: { label: string; onRetry: () => void }) {
  return (
    <p className="m-0 mb-3 text-[13px] flex items-center gap-2" style={{ color: "var(--err)" }}>
      Unable to load {label}.
      <RetryButton onRetry={onRetry} />
    </p>
  );
}
