"use client";

import React from "react";

import { AuditLogRead } from "../schemas";
import { formatAction } from "../utils";

type Props = {
  logs: AuditLogRead[];
  showOrg: boolean;
};

export function AuditLogTable({ logs, showOrg }: Props) {
  const [expanded, setExpanded] = React.useState<Set<string>>(new Set());

  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const columns = ["Time", "Actor", "Action", "Target", ...(showOrg ? ["Org"] : [])];
  const colSpan = columns.length;

  if (logs.length === 0) {
    return (
      <div className="af-card overflow-hidden">
        <div
          className="p-10 text-center text-[0.875rem]"
          style={{ color: "var(--ink-3)" }}
        >
          No audit entries match these filters.
        </div>
      </div>
    );
  }

  return (
    <div className="af-card overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr style={{ borderBottom: "1px solid var(--line)" }}>
              {columns.map((h) => (
                <th
                  key={h}
                  className="px-5 py-3 text-[0.75rem] font-medium uppercase tracking-wider"
                  style={{ color: "var(--ink-4)" }}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {logs.map((log) => {
              const changes = changedEntries(log.changedFields);
              const canExpand = changes.length > 0;
              const isOpen = expanded.has(log.id);
              return (
                <React.Fragment key={log.id}>
                  <tr
                    className="transition-colors"
                    style={{
                      borderBottom: "1px solid var(--line)",
                      cursor: canExpand ? "pointer" : "default",
                    }}
                    onClick={() => canExpand && toggle(log.id)}
                    onMouseEnter={(e) =>
                      (e.currentTarget.style.background = "var(--bg-soft)")
                    }
                    onMouseLeave={(e) => (e.currentTarget.style.background = "")}
                  >
                    <td
                      className="px-5 py-3 text-[0.8125rem] whitespace-nowrap"
                      style={{ color: "var(--ink-3)" }}
                    >
                      {formatTime(log.createdAt)}
                    </td>
                    <td className="px-5 py-3">
                      <div
                        className="text-[0.875rem]"
                        style={{ color: "var(--ink)" }}
                      >
                        {log.actorName ?? log.actorEmail ?? "—"}
                      </div>
                      {log.actorEmail && log.actorName && (
                        <div
                          className="text-[0.75rem] mt-0.5"
                          style={{ color: "var(--ink-4)" }}
                        >
                          {log.actorEmail}
                        </div>
                      )}
                    </td>
                    <td className="px-5 py-3">
                      <div
                        className="flex items-center gap-1.5 text-[0.875rem]"
                        style={{ color: "var(--ink)" }}
                      >
                        {canExpand && <span>{isOpen ? "▾" : "▸"}</span>}
                        {formatAction(log.action)}
                      </div>
                      <div
                        className="text-[0.6875rem] font-mono mt-0.5"
                        style={{ color: "var(--ink-5)" }}
                      >
                        {log.action}
                      </div>
                    </td>
                    <td className="px-5 py-3">
                      <div
                        className="text-[0.8125rem]"
                        style={{ color: "var(--ink-2)" }}
                      >
                        {log.targetLabel ?? "—"}
                      </div>
                      {log.targetType && (
                        <div
                          className="text-[0.6875rem] mt-0.5"
                          style={{ color: "var(--ink-5)" }}
                        >
                          {log.targetType}
                        </div>
                      )}
                    </td>
                    {showOrg && (
                      <td
                        className="px-5 py-3 text-[0.8125rem]"
                        style={{ color: "var(--ink-3)" }}
                      >
                        {log.organizationName ??
                          (log.organizationId ? shortId(log.organizationId) : "—")}
                      </td>
                    )}
                  </tr>

                  {isOpen && canExpand && (
                    <tr style={{ background: "var(--bg-elev)" }}>
                      <td colSpan={colSpan} className="px-5 py-3">
                        <div className="flex flex-col gap-1.5">
                          {changes.map(({ field, old, next }) => (
                            <div
                              key={field}
                              className="text-[0.8125rem] flex flex-wrap items-center gap-2"
                            >
                              <span
                                className="font-mono"
                                style={{ color: "var(--ink-3)" }}
                              >
                                {field}
                              </span>
                              <span style={{ color: "var(--ink-5)" }}>
                                {formatValue(old)}
                              </span>
                              <span style={{ color: "var(--ink-5)" }}>→</span>
                              <span style={{ color: "var(--ink)" }}>
                                {formatValue(next)}
                              </span>
                            </div>
                          ))}
                        </div>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

type ChangeEntry = { field: string; old: unknown; next: unknown };

function changedEntries(
  changed: Record<string, unknown> | null | undefined,
): ChangeEntry[] {
  if (!changed) return [];
  return Object.entries(changed).map(([field, value]) => {
    if (value && typeof value === "object" && "new" in (value as object)) {
      const v = value as { old?: unknown; new?: unknown };
      return { field, old: v.old, next: v.new };
    }
    // Redacted marker (a bare string) — show it on the "new" side.
    return { field, old: undefined, next: value };
  });
}

function formatValue(value: unknown): string {
  if (value === undefined) return "∅";
  if (value === null) return "null";
  if (typeof value === "string") return value === "" ? '""' : value;
  return JSON.stringify(value);
}

function shortId(id: string): string {
  return `${id.split("-")[0]}…`;
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}
