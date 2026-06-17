"use client";

import React, { useState } from "react";
import { useToolCalls, type ToolCallFilters } from "../hooks/use-tool-calls";
import { TOOL_CALLS_PAGE_SIZE } from "../utils";
import type { Agent, ToolCall } from "../schemas";
import { Pagination } from "./pagination";

interface ToolCallsTabProps {
  agent: Agent;
}

export function ToolCallsTab({ agent }: ToolCallsTabProps) {
  const [filters, setFilters] = useState<ToolCallFilters>({
    toolName: "",
    status: "",
    fromDate: "",
    toDate: "",
  });
  const [page, setPage] = useState(1);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const { data, isLoading, error } = useToolCalls(agent.id, filters, page);
  const totalPages = data ? Math.ceil(data.total / TOOL_CALLS_PAGE_SIZE) : 0;
  const hasFilters = !!(filters.toolName || filters.status || filters.fromDate || filters.toDate);

  function setFilter<K extends keyof ToolCallFilters>(key: K, value: ToolCallFilters[K]) {
    setFilters((prev) => ({ ...prev, [key]: value }));
    setPage(1);
  }

  function toggleExpanded(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex gap-2 flex-wrap">
        <input
          className="af-input"
          style={{ width: "12rem" }}
          placeholder="Filter by tool name"
          value={filters.toolName}
          onChange={(e) => setFilter("toolName", e.target.value)}
        />
        <select
          className="af-input"
          style={{ width: "11rem" }}
          value={filters.status}
          onChange={(e) => setFilter("status", e.target.value as ToolCallFilters["status"])}
        >
          <option value="">All statuses</option>
          <option value="PENDING">Pending</option>
          <option value="SUCCESS">Success</option>
          <option value="ERROR">Error</option>
        </select>
        <input
          type="datetime-local"
          className="af-input"
          style={{ width: "13rem" }}
          value={filters.fromDate}
          onChange={(e) => setFilter("fromDate", e.target.value)}
          title="From date"
        />
        <input
          type="datetime-local"
          className="af-input"
          style={{ width: "13rem" }}
          value={filters.toDate}
          onChange={(e) => setFilter("toDate", e.target.value)}
          title="To date"
        />
      </div>

      {isLoading && <ToolCallsSkeleton />}

      {error && (
        <div
          className="rounded-xl px-5 py-4 text-[0.875rem]"
          style={{ background: "var(--err-soft)", color: "var(--err)" }}
        >
          Failed to load tool calls. Retrying…
        </div>
      )}

      {data && (
        <>
          <div className="text-[0.8125rem]" style={{ color: "var(--ink-4)" }}>
            {data.total === 0
              ? hasFilters ? "No tool calls match your filters" : "No tool calls yet"
              : `${data.total} tool call${data.total === 1 ? "" : "s"}`}
          </div>

          {data.items.length > 0 && (
            <div className="af-card overflow-hidden" style={{ padding: 0 }}>
              <table className="w-full" style={{ fontSize: "0.8125rem", borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ borderBottom: "1px solid var(--line)" }}>
                    <Th>Time</Th>
                    <Th>Tool</Th>
                    <Th>Status</Th>
                    <Th>Duration</Th>
                    <th style={{ width: "2.5rem" }} />
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((item, i) => (
                    <React.Fragment key={item.id}>
                      <tr
                        style={{
                          borderTop: i > 0 ? "1px solid var(--line)" : undefined,
                          cursor: "default",
                        }}
                        className="af-hover-bg"
                        onClick={() => toggleExpanded(item.id)}
                      >
                        <Td>
                          <span className="font-mono" style={{ color: "var(--ink-3)" }}>
                            {formatTime(item.occurredAt)}
                          </span>
                        </Td>
                        <Td>
                          <span className="font-mono" style={{ color: "var(--ink)" }}>
                            {item.toolName}
                          </span>
                        </Td>
                        <Td>
                          <StatusBadge status={item.status} />
                        </Td>
                        <Td style={{ color: "var(--ink-3)" }}>
                          {item.durationMs != null ? formatDuration(item.durationMs) : "—"}
                        </Td>
                        <td className="px-3 py-3 text-right">
                          <ChevronIcon open={expanded.has(item.id)} />
                        </td>
                      </tr>
                      {expanded.has(item.id) && (
                        <tr style={{ borderTop: "1px solid var(--line)", background: "var(--bg-soft)" }}>
                          <td colSpan={5} className="px-4 pb-4 pt-3">
                            <div className="flex flex-col gap-3">
                              <JsonSection label="Arguments" value={item.arguments} />
                              {item.result != null && (
                                <JsonSection label="Result" value={item.result} />
                              )}
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <Pagination page={page} totalPages={totalPages} onPageChange={setPage} align="end" />
        </>
      )}
    </div>
  );
}

function Th({ children }: { children: React.ReactNode }) {
  return (
    <th
      className="text-left px-4 py-3 font-medium"
      style={{ color: "var(--ink-3)", fontWeight: 500 }}
    >
      {children}
    </th>
  );
}

function Td({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <td className="px-4 py-3" style={style}>
      {children}
    </td>
  );
}

function StatusBadge({ status }: { status: ToolCall["status"] }) {
  const cfg = {
    PENDING: { label: "Pending", color: "var(--warn)", bg: "var(--warn-soft)" },
    SUCCESS: { label: "Success", color: "var(--ok)", bg: "var(--ok-soft)" },
    ERROR:   { label: "Error",   color: "var(--err)", bg: "var(--err-soft)" },
  }[status];

  return (
    <span
      style={{
        display: "inline-block",
        padding: "2px 8px",
        borderRadius: "999px",
        fontSize: "0.75rem",
        fontWeight: 500,
        color: cfg.color,
        background: cfg.bg,
      }}
    >
      {cfg.label}
    </span>
  );
}

function ChevronIcon({ open }: { open: boolean }) {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 14 14"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{
        color: "var(--ink-4)",
        transform: open ? "rotate(180deg)" : undefined,
        transition: "transform .15s",
      }}
    >
      <path d="M3 5l4 4 4-4" />
    </svg>
  );
}

function JsonSection({ label, value }: { label: string; value: unknown }) {
  return (
    <div>
      <div
        className="text-[0.75rem] font-medium mb-1.5 uppercase tracking-wide"
        style={{ color: "var(--ink-4)" }}
      >
        {label}
      </div>
      <pre
        className="rounded-lg px-3 py-2.5 overflow-x-auto text-[0.75rem] font-mono leading-relaxed"
        style={{ background: "var(--bg-sunken)", color: "var(--ink-2)" }}
      >
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}

function ToolCallsSkeleton() {
  return (
    <div className="af-card animate-pulse" style={{ padding: 0 }}>
      {[...Array(4)].map((_, i) => (
        <div
          key={i}
          className="px-4 py-3 flex gap-4"
          style={{ borderTop: i > 0 ? "1px solid var(--line)" : undefined }}
        >
          <div className="h-4 w-28 rounded" style={{ background: "var(--bg-soft)" }} />
          <div className="h-4 w-20 rounded" style={{ background: "var(--bg-soft)" }} />
          <div className="h-4 w-14 rounded" style={{ background: "var(--bg-soft)" }} />
          <div className="h-4 w-12 rounded" style={{ background: "var(--bg-soft)" }} />
        </div>
      ))}
    </div>
  );
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const isToday = d.toDateString() === now.toDateString();
  const time = d.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
  if (isToday) return time;
  return (
    d.toLocaleDateString("en-US", { month: "short", day: "numeric" }) + " " + time
  );
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}
