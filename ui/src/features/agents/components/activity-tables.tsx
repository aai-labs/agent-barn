"use client";

import type { ReactNode } from "react";

import { Badge } from "@/components/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  formatCallSpend,
  formatDuration,
  formatModelLabel,
  formatSpend,
  formatTokens,
} from "@/features/costs/format";
import { formatBucketLong } from "@/features/platform-stats/format";
import type { Granularity } from "@/features/platform-stats/schemas";

import type { ActivityBucket, AgentActivityCall, AgentWake } from "../schemas";
import { TRIGGER_HINT, TRIGGER_LABEL, formatClock, formatSpan, formatTokenRange } from "./activity-format";

export function ByPeriodTable({
  buckets,
  granularity,
  onSelect,
}: {
  buckets: ActivityBucket[];
  granularity: Granularity;
  onSelect: (bucket: ActivityBucket) => void;
}) {
  const busy = buckets.filter((bucket) => bucket.calls > 0);
  if (busy.length === 0) return <Empty>No model calls in this window.</Empty>;

  return (
    <Table
      columns={[
        { label: "Period" },
        { label: "Calls", align: "right" },
        { label: "Prompt tokens", align: "right" },
        { label: "Completion tokens", align: "right" },
        { label: "Spend", align: "right" },
      ]}
    >
      {busy.map((bucket) => (
        <tr key={bucket.bucket} style={{ borderTop: "1px solid var(--line)" }}>
          <Td>{formatBucketLong(bucket.bucket, granularity)}</Td>
          <Td align="right">
            <DrillButton
              onClick={() => onSelect(bucket)}
              label={`${bucket.calls}`}
              ariaLabel={`Show the ${callCount(bucket.calls)} from ${formatBucketLong(bucket.bucket, granularity)}`}
            />
          </Td>
          <Td align="right" muted>
            {formatTokens(bucket.promptTokens)}
          </Td>
          <Td align="right" muted>
            {formatTokens(bucket.completionTokens)}
          </Td>
          <Td align="right">{formatSpend(bucket.spend)}</Td>
        </tr>
      ))}
    </Table>
  );
}

export function WakesTable({
  wakes,
  onSelect,
}: {
  wakes: AgentWake[];
  onSelect: (wake: AgentWake) => void;
}) {
  if (wakes.length === 0) return <Empty>No wakes in this window.</Empty>;

  return (
    <Table
      columns={[
        { label: "Started" },
        { label: "What started it" },
        { label: "Calls", align: "right" },
        { label: "Prompt tokens per call", align: "right" },
        { label: "Spend", align: "right" },
        { label: "Model" },
      ]}
    >
      {wakes.map((wake) => {
        const span = formatSpan(wake.startedAt, wake.endedAt);
        return (
          <tr key={wake.startedAt} style={{ borderTop: "1px solid var(--line)" }}>
            <Td>
              <span className="font-mono">{formatClock(wake.startedAt)}</span>
              {span && (
                <span className="ml-2 text-[11px]" style={{ color: "var(--ink-4)" }}>
                  {span}
                </span>
              )}
            </Td>
            <Td>
              <span title={TRIGGER_HINT[wake.trigger]}>
                <Badge variant={wake.trigger === "background" ? "warn" : "neutral"}>
                  {TRIGGER_LABEL[wake.trigger]}
                </Badge>
              </span>
            </Td>
            <Td align="right">
              <DrillButton
                onClick={() => onSelect(wake)}
                label={`${wake.calls}`}
                ariaLabel={`Show the ${callCount(wake.calls)} in the wake at ${formatClock(wake.startedAt)}`}
              />
            </Td>
            <Td align="right" muted>
              {formatTokenRange(wake.minPromptTokens, wake.maxPromptTokens, formatTokens)}
            </Td>
            <Td align="right">{formatSpend(wake.spend)}</Td>
            <Td muted>{wake.models.map(formatModelLabel).join(", ") || "—"}</Td>
          </tr>
        );
      })}
    </Table>
  );
}

export function CallsTable({ calls }: { calls: AgentActivityCall[] }) {
  if (calls.length === 0) return <Empty>No calls in this slice.</Empty>;

  return (
    <Table
      columns={[
        { label: "Time" },
        { label: "Model" },
        { label: "Status" },
        { label: "Prompt", align: "right" },
        { label: "Completion", align: "right" },
        { label: "Duration", align: "right" },
        { label: "Spend", align: "right" },
      ]}
    >
      {calls.map((call) => (
        <tr key={call.requestId} style={{ borderTop: "1px solid var(--line)" }}>
          <Td>
            <span className="font-mono">{formatClock(call.occurredAt)}</span>
          </Td>
          <Td muted>{formatModelLabel(call.model)}</Td>
          <Td>
            {call.status === "success" ? (
              <span style={{ color: "var(--ink-3)" }}>Success</span>
            ) : (
              <Badge variant="danger">{call.status}</Badge>
            )}
          </Td>
          <Td align="right" muted>
            {formatTokens(call.promptTokens)}
          </Td>
          <Td align="right" muted>
            {formatTokens(call.completionTokens)}
          </Td>
          <Td align="right" muted>
            {formatDuration(call.requestDurationMs)}
          </Td>
          <Td align="right">{formatCallSpend(call.spend)}</Td>
        </tr>
      ))}
    </Table>
  );
}

export function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="flex flex-col gap-2">
      {Array.from({ length: rows }, (_, index) => (
        <Skeleton key={index} className="h-8 w-full" />
      ))}
    </div>
  );
}

type Column = { label: string; align?: "left" | "right" };

function Table({ columns, children }: { columns: Column[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-[13px]">
        <thead>
          <tr>
            {columns.map((column) => (
              <th
                key={column.label}
                scope="col"
                className={`px-3 py-2.5 first:pl-0 last:pr-0 whitespace-nowrap font-medium ${column.align === "right" ? "text-right" : "text-left"}`}
                style={{ borderBottom: "1px solid var(--line)", color: "var(--ink-3)" }}
              >
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

function Td({
  children,
  align = "left",
  muted = false,
}: {
  children: ReactNode;
  align?: "left" | "right";
  muted?: boolean;
}) {
  return (
    <td
      className={`px-3 py-2.5 first:pl-0 last:pr-0 ${align === "right" ? "text-right tabular-nums" : "text-left"}`}
      style={{ color: muted ? "var(--ink-3)" : "var(--ink)" }}
    >
      {children}
    </td>
  );
}

/**
 * The count is the way in: pressing it narrows everything below to that slice.
 * Counts repeat down a column, so the accessible name says which slice and what
 * pressing it does, not just the number.
 */
function DrillButton({
  onClick,
  label,
  ariaLabel,
}: {
  onClick: () => void;
  label: string;
  ariaLabel: string;
}) {
  return (
    <button
      type="button"
      aria-label={ariaLabel}
      onClick={onClick}
      className="rounded-md px-1.5 py-0.5 tabular-nums underline underline-offset-2 hover:bg-[var(--bg-soft)]"
      style={{ color: "var(--accent-ink)" }}
    >
      {label}
    </button>
  );
}

function callCount(calls: number): string {
  return `${calls.toLocaleString("en-US")} ${calls === 1 ? "call" : "calls"}`;
}

function Empty({ children }: { children: ReactNode }) {
  return (
    <p className="m-0 py-2 text-[12.5px]" style={{ color: "var(--ink-4)" }}>
      {children}
    </p>
  );
}
