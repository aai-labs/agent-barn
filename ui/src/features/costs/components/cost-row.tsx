"use client";

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

      {/* Where a cost came from — LiteLLM directly, or recovered from OpenRouter
          afterwards — is our plumbing, not something a reader can act on, so the
          row shows the amount and nothing else. The `healed` flag is still on the
          record for support and debugging. */}
      <span
        className="text-right font-medium"
        style={{ color: failed ? "var(--ink-4)" : "var(--ink)" }}
      >
        {failed ? "—" : formatCallSpend(record.spend)}
      </span>
    </div>
  );
}
