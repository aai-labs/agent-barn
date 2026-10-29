"use client";

import { useState } from "react";
import { Settings2, TriangleAlert } from "lucide-react";

import { formatPercent } from "@/features/costs/format";
import { ALL_CEILINGS, CapacityLimitsDialog } from "@/features/resource-usage/components/capacity-limits-dialog";
import { UsageMeter } from "@/features/resource-usage/components/usage-meter";
import type { ResourceLimits } from "@/features/resource-usage/schemas";

import type { CapacityLine, SourceState } from "../schemas";
import { capacityTone, formatQuantity, TONE_COLOR } from "../utils";
import { EmptyRow, Section } from "./section";

/** What each line stops when it is full, so a warning says what will fail. */
const BLOCKS: Record<string, string> = {
  "requests.storage": "New agents can't get a volume",
  persistentvolumeclaims: "New agents can't get a volume",
  pods: "New pods are refused",
};

function lineText(line: CapacityLine): string {
  const hard = line.hard === null ? null : formatQuantity(line.hard, line.unit);
  if (line.level === "ceiling_out_of_date") {
    return `Above the ${hard} you entered, so the entered quota is probably out of date.`;
  }
  if (line.hard === null) return line.source === "entered" ? "No quota entered" : "No limit";
  if (line.used === null) return `In use not available · quota ${hard}`;
  if (line.ratio === null) return `Quota ${hard}`;
  return `${formatPercent(line.ratio)} of ${hard}`;
}

function warningText(line: CapacityLine): string {
  const blocks = BLOCKS[line.resource] ?? "New pods may be refused";
  if (line.level === "ceiling_out_of_date") {
    return `${line.resource} is above the quota you entered. Check the namespace quota and update it.`;
  }
  const share = line.ratio === null ? "at its limit" : `at ${formatPercent(line.ratio)} of its quota`;
  return line.level === "critical"
    ? `${line.resource} is ${share}. ${blocks} once it is full.`
    : `${line.resource} is ${share}. Room is running low.`;
}

/**
 * Every quota line: the namespace's own figures when its ResourceQuota can be read, the
 * ceilings an administrator entered otherwise. Storage and pods come first, since those are
 * what stopped new agents before.
 */
export function CapacityPanel({
  lines,
  ceilings,
  quotaState,
}: {
  lines: CapacityLine[];
  ceilings: ResourceLimits;
  quotaState: SourceState | undefined;
}) {
  const [open, setOpen] = useState(false);
  // Bumped on each opening, so the dialog starts from what is saved.
  const [openings, setOpenings] = useState(0);
  const fromQuota = lines.some((line) => line.source === "quota");
  const warnings = lines.filter((line) => ["warning", "critical", "ceiling_out_of_date"].includes(line.level));
  const hasRed = warnings.some((line) => line.level !== "warning");

  function openDialog() {
    setOpenings((count) => count + 1);
    setOpen(true);
  }

  const description = fromQuota
    ? "Read from the namespace's ResourceQuota."
    : quotaState === "forbidden"
      ? "The service account can't read the namespace's ResourceQuota, so these compare the quota you entered with what the platform counts itself."
      : "Compared with the quota you entered. Storage is every volume claim's request, and pods are every pod still running or starting.";

  return (
    <Section
      title="Capacity"
      testId="environment-capacity"
      description={description}
      actions={
        <button type="button" className="af-btn af-btn-sm" onClick={openDialog} data-testid="environment-quota-open">
          <Settings2 size={14} /> Namespace quota
        </button>
      }
    >
      {warnings.length > 0 && (
        <div
          className="af-card mb-3 flex items-start gap-3 p-4"
          role="alert"
          style={{ borderColor: hasRed ? "var(--err)" : "var(--warn)" }}
          data-testid="environment-capacity-warning"
        >
          <TriangleAlert
            size={18}
            className="mt-0.5 flex-shrink-0"
            style={{ color: hasRed ? "var(--err)" : "var(--warn)" }}
          />
          <div className="min-w-0">
            <p className="m-0 text-[14px] font-semibold" style={{ color: "var(--ink)" }}>
              {hasRed ? "The namespace is at or near its limit" : "The namespace is getting full"}
            </p>
            {warnings.map((line) => (
              <p key={line.resource} className="m-0 mt-1 text-[13px] leading-relaxed" style={{ color: "var(--ink-3)" }}>
                {warningText(line)}
              </p>
            ))}
          </div>
        </div>
      )}

      {lines.length === 0 ? (
        <EmptyRow>No quota lines to show.</EmptyRow>
      ) : (
        <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(min(200px, 100%), 1fr))" }}>
          {lines.map((line) => (
            <div
              key={line.resource}
              className="af-card min-w-0 px-4 py-3.5"
              data-testid={`capacity-line-${line.resource}`}
              data-level={line.level}
            >
              <p className="m-0 mb-1 truncate font-mono text-[12px]" style={{ color: "var(--ink-4)" }}>
                {line.resource}
              </p>
              <p
                className="m-0 truncate text-[20px] font-semibold"
                style={{ color: line.level === "ok" || line.level === "unknown" ? "var(--ink)" : TONE_COLOR[capacityTone(line.level)] }}
              >
                {line.used === null ? "—" : formatQuantity(line.used, line.unit)}
              </p>
              <p className="m-0 mt-0.5 text-[12px]" style={{ color: "var(--ink-4)" }}>
                {lineText(line)}
              </p>
              {line.ratio !== null && line.level !== "ceiling_out_of_date" && (
                <UsageMeter ratio={line.ratio} label={`${line.resource} against its quota`} className="mt-2" />
              )}
            </div>
          ))}
        </div>
      )}

      <CapacityLimitsDialog
        key={openings}
        ceilings={ceilings}
        fields={ALL_CEILINGS}
        open={open}
        onOpenChange={setOpen}
      />
    </Section>
  );
}
