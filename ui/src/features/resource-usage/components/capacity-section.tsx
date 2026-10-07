"use client";

import { useState } from "react";
import { Settings2, TriangleAlert } from "lucide-react";

import { formatPercent } from "@/features/costs/format";

import { formatBytes, formatCores } from "../format";
import type { PlatformCapacity } from "../schemas";
import { capacityStatus, type CapacityState, type CapacityStatus } from "../utils";
import { CapacityLimitsDialog } from "./capacity-limits-dialog";
import { UsageMeter } from "./usage-meter";

interface Measure {
  /** The quota's own line, which also names the card's test id. */
  key: "limits-memory" | "limits-cpu" | "requests-memory" | "requests-cpu";
  label: string;
  /** What the quota calls it, for the warning text. */
  noun: string;
  committed: number | null;
  limit: number | null;
  format: (value: number) => string;
}

function formatCpu(value: number): string {
  return `${formatCores(value)} cores`;
}

const WARNING_STATES: CapacityState[] = ["warn", "critical", "over"];

const VALUE_COLOR: Record<CapacityState, string> = {
  unset: "var(--ink)",
  unknown: "var(--ink)",
  ok: "var(--ink)",
  warn: "var(--warn)",
  critical: "var(--err)",
  over: "var(--err)",
};

/** One sentence per resource that needs attention, plain enough to act on. */
function warningText(measure: Measure, status: CapacityStatus): string {
  const committed = measure.format(measure.committed ?? 0);
  const limit = measure.format(measure.limit ?? 0);
  switch (status.state) {
    case "over":
      return `${measure.noun} committed (${committed}) are above the ${limit} quota you entered, so what you entered is probably out of date. Check the namespace quota.`;
    case "critical":
      return `${measure.noun} committed are ${formatPercent(status.ratio ?? 1)} of the ${limit} quota (${committed}). New agents may fail to start.`;
    default:
      return `${measure.noun} committed are ${formatPercent(status.ratio ?? 0)} of the ${limit} quota (${committed}). Room for new agents is running low.`;
  }
}

/**
 * What the namespace has committed, in limits and in requests, against the quota ceilings
 * an administrator entered.
 *
 * The quota counts what containers are allowed to use and what they ask for, not what they
 * use, so this is about room for new agents, not about the CPU and memory in use above. A
 * new pod is refused when any one of the four would go over. It always renders, even when
 * the usage source is down: the ceilings come from the database and stay editable.
 */
export function CapacitySection({ capacity }: { capacity: PlatformCapacity }) {
  const [open, setOpen] = useState(false);
  // Bumped on each opening, so the dialog starts from what is saved and without the last error.
  const [openings, setOpenings] = useState(0);

  const measures: Measure[] = [
    {
      key: "limits-memory",
      label: "Memory limits committed",
      noun: "Memory limits",
      committed: capacity.committedLimitsMemoryBytes,
      limit: capacity.limitsMemoryBytes,
      format: formatBytes,
    },
    {
      key: "limits-cpu",
      label: "CPU limits committed",
      noun: "CPU limits",
      committed: capacity.committedLimitsCpuCores,
      limit: capacity.limitsCpuCores,
      format: formatCpu,
    },
    {
      key: "requests-memory",
      label: "Memory requests committed",
      noun: "Memory requests",
      committed: capacity.committedRequestsMemoryBytes,
      limit: capacity.requestsMemoryBytes,
      format: formatBytes,
    },
    {
      key: "requests-cpu",
      label: "CPU requests committed",
      noun: "CPU requests",
      committed: capacity.committedRequestsCpuCores,
      limit: capacity.requestsCpuCores,
      format: formatCpu,
    },
  ];
  const statuses = measures.map((measure) => capacityStatus(measure.committed, measure.limit));
  const warnings = measures
    .map((measure, index) => ({ measure, status: statuses[index] }))
    .filter(({ status }) => WARNING_STATES.includes(status.state));
  const hasRed = warnings.some(({ status }) => status.state !== "warn");

  function openDialog() {
    setOpenings((count) => count + 1);
    setOpen(true);
  }

  return (
    <section className="mb-6" data-testid="platform-capacity">
      <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
        {/* Takes the free width, so a long sentence wraps beside the button, not pushes it down. */}
        <div className="min-w-0 flex-1 basis-[28rem]">
          <h2 className="m-0 text-[14px] font-semibold" style={{ color: "var(--ink)" }}>
            Capacity
          </h2>
          <p className="m-0 mt-0.5 text-[12.5px]" style={{ color: "var(--ink-4)" }}>
            The limits and requests of every pod, added up, against the quota you entered. A new pod is refused when any one of the four would go over.
          </p>
        </div>
        <button type="button" className="af-btn af-btn-sm" onClick={openDialog} data-testid="capacity-limits-open">
          <Settings2 size={14} /> Namespace quota
        </button>
      </div>

      {warnings.length > 0 && (
        <div
          className="af-card mb-3 flex items-start gap-3 p-4"
          role="alert"
          style={{ borderColor: hasRed ? "var(--err)" : "var(--warn)" }}
          data-testid="capacity-warning"
          data-tone={hasRed ? "err" : "warn"}
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
            {warnings.map(({ measure, status }) => (
              <p
                key={measure.key}
                className="m-0 mt-1 text-[13px] leading-relaxed"
                style={{ color: "var(--ink-3)" }}
                data-testid={`capacity-warning-${measure.key}`}
              >
                {warningText(measure, status)}
              </p>
            ))}
          </div>
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        {measures.map((measure, index) => {
          const status = statuses[index];
          return (
            <div
              key={measure.key}
              className="af-card px-4 py-3.5"
              data-testid={`capacity-${measure.key}`}
              data-state={status.state}
            >
              <p className="m-0 mb-1 text-[12px]" style={{ color: "var(--ink-4)" }}>
                {measure.label}
              </p>
              <p
                className="m-0 truncate text-[20px] font-semibold"
                style={{ color: VALUE_COLOR[status.state] }}
              >
                {measure.committed !== null ? measure.format(measure.committed) : "—"}
              </p>
              <p className="m-0 mt-0.5 text-[12px]" style={{ color: "var(--ink-4)" }}>
                {status.state === "unset" && "No quota entered"}
                {status.state === "unknown" &&
                  `Committed figure not available · quota ${measure.format(measure.limit ?? 0)}`}
                {status.ratio !== null &&
                  `${formatPercent(status.ratio)} of the ${measure.format(measure.limit ?? 0)} quota`}
              </p>
              {status.state === "unset" && (
                <button
                  type="button"
                  className="mt-2 text-[12px] underline underline-offset-2"
                  style={{ color: "var(--ink-3)" }}
                  onClick={openDialog}
                >
                  Enter quota
                </button>
              )}
              {status.ratio !== null && (
                <UsageMeter ratio={status.ratio} label={`${measure.label} against the quota`} className="mt-2" />
              )}
            </div>
          );
        })}
      </div>

      <CapacityLimitsDialog key={openings} capacity={capacity} open={open} onOpenChange={setOpen} />
    </section>
  );
}
