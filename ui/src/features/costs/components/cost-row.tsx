"use client";

import { Sparkles } from "lucide-react";

import { formatCallSpend, formatDuration, formatTokens } from "../format";
import type { CostRecord, PlatformCostRecord } from "../schemas";

interface CostRowProps {
  record: CostRecord | PlatformCostRecord;
  grid: string;
  showOrganization: boolean;
}

export function CostRow({ record, grid, showOrganization }: CostRowProps) {
  const organizationName =
    "organizationName" in record ? record.organizationName : null;
  const failed = record.status !== "success";

  return (
    <div
      className={`grid ${grid} gap-3 px-4 py-2.5 items-center text-[13px] border-t`}
      style={{ borderColor: "var(--line)" }}
      data-testid="cost-row"
    >
      <span style={{ color: "var(--ink-3)" }} title={record.occurredAt}>
        {new Date(record.occurredAt).toLocaleString("en-US", {
          month: "short",
          day: "numeric",
          hour: "2-digit",
          minute: "2-digit",
        })}
      </span>

      <span className="truncate" style={{ color: "var(--ink)" }} title={record.model}>
        {record.model.split("/").at(-1)}
      </span>

      <span
        className="truncate"
        style={{ color: record.agentName ? "var(--ink-2)" : "var(--ink-4)" }}
        title={record.agentName ?? "Unattributed"}
      >
        {record.agentName ?? "Unattributed"}
      </span>

      {showOrganization && (
        <span
          className="truncate"
          style={{ color: organizationName ? "var(--ink-2)" : "var(--ink-4)" }}
          title={organizationName ?? "Unattributed"}
        >
          {organizationName ?? "Unattributed"}
        </span>
      )}

      <span className="text-right" style={{ color: "var(--ink-3)" }}>
        {formatTokens(record.totalTokens)}
      </span>

      <span className="text-right" style={{ color: "var(--ink-4)" }}>
        {formatDuration(record.requestDurationMs)}
      </span>

      <span
        className="text-right font-medium flex items-center justify-end gap-1"
        style={{ color: failed ? "var(--ink-4)" : "var(--ink)" }}
      >
        {/* A recovered cost is worth marking: it is why a historical total can
            go up between two views of the same period. */}
        {record.healed && (
          <Sparkles
            size={11}
            style={{ color: "var(--acc)" }}
            aria-label="Cost recovered from OpenRouter"
          />
        )}
        {failed ? "—" : formatCallSpend(record.spend)}
      </span>
    </div>
  );
}
