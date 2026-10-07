"use client";

import { Fragment } from "react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

import { formatBytes, formatCores } from "../format";
import type { PlatformOrganizationUsage } from "../schemas";

/** Plain-English answer to "why is there a row with no organization?". */
const NO_LIVE_AGENT_HINT =
  "Containers that are still running but belong to no live agent: the agent was deleted, " +
  "or this database never knew it. They still use the cluster's memory and CPU quota.";

// One compact line per row at every width. Written out whole, apart from the template
// below, so Tailwind finds both classes. The reporting count is the first thing to go on
// a phone: name, memory and CPU are what the row is for.
const ROW_COLUMNS =
  "grid-cols-[minmax(0,1fr)_72px_84px] sm:grid-cols-[minmax(140px,1fr)_140px_90px_90px]";

/** Organizations listed when the page is not narrowed to one. */
const TOP_COUNT = 5;

interface OrganizationsByUsageProps {
  organizations: PlatformOrganizationUsage[];
  activeOrganizationId: string | null;
  onSelect: (organization: { id: string; name: string } | null) => void;
}

/**
 * Organizations ranked by memory in use, doubling as a one-click filter.
 *
 * Narrowed to one organization, it shows only that one. Otherwise it shows the top five.
 * The no-live-agent row is kept beside them whatever the count: without it the rows would
 * not add up to the platform total above them, and leaked containers would be invisible.
 * It is the one row that is not an organization, so it does not use up one of the five.
 */
export function OrganizationsByUsage({
  organizations,
  activeOrganizationId,
  onSelect,
}: OrganizationsByUsageProps) {
  const named = organizations.filter((row) => row.organizationId !== null);
  const noLiveAgent = organizations.find((row) => row.organizationId === null);
  // A narrowed page leaves the no-live-agent row out too: its totals do not include it.
  const shown = activeOrganizationId
    ? named.filter((row) => row.organizationId === activeOrganizationId)
    : [...named.slice(0, TOP_COUNT), ...(noLiveAgent ? [noLiveAgent] : [])];
  const hiddenCount = activeOrganizationId ? 0 : named.length - TOP_COUNT;

  if (shown.length === 0) return null;

  const top = Math.max(...shown.map((row) => row.memoryWorkingSetBytes ?? 0), 0);

  return (
    <div className="af-card mb-6 p-4" data-testid="organizations-by-usage">
      <h2 className="m-0 mb-3 text-[14px] font-semibold" style={{ color: "var(--ink)" }}>
        Organizations by memory
      </h2>
      <div className="flex flex-col">
        {shown.map((organization) => {
          const id = organization.organizationId;
          const isActive = id !== null && id === activeOrganizationId;
          const isNoLiveAgent = id === null;
          const name = organization.organizationName ?? "No live agent";
          const memory = organization.memoryWorkingSetBytes ?? 0;
          const width = top > 0 ? (memory / top) * 100 : 0;

          const row = (
            <button
              type="button"
              // Marked rather than `disabled`: a disabled button emits no pointer events
              // and takes no focus, which would put its tooltip out of reach of both the
              // mouse and the keyboard.
              aria-disabled={isNoLiveAgent}
              aria-pressed={isNoLiveAgent ? undefined : isActive}
              onClick={() => {
                if (isNoLiveAgent) return;
                onSelect(isActive ? null : { id: id!, name });
              }}
              data-testid="organization-usage-row"
              data-organization-id={id ?? "none"}
              className={`relative grid ${ROW_COLUMNS} items-center gap-3 rounded px-2 py-2 text-left text-[13px]${
                isNoLiveAgent ? " cursor-default" : ""
              }`}
              style={{ background: isActive ? "var(--surface-2)" : "transparent" }}
            >
              <span
                className="pointer-events-none absolute inset-y-1 left-0 rounded"
                style={{ width: `${width}%`, background: "var(--ink-5)", opacity: 0.12 }}
              />
              <span
                className="relative truncate"
                style={{ color: id ? "var(--ink)" : "var(--ink-4)" }}
                title={name}
              >
                {name}
              </span>
              <span
                className="relative hidden whitespace-nowrap text-right sm:block"
                style={{ color: "var(--ink-4)" }}
              >
                {isNoLiveAgent
                  ? `${organization.agentsReporting ?? 0} ${
                      organization.agentsReporting === 1 ? "container" : "containers"
                    }`
                  : `${organization.agentsReporting ?? 0} of ${organization.agentsWithContainer} reporting`}
              </span>
              <span className="relative text-right font-medium" style={{ color: "var(--ink)" }}>
                {formatBytes(memory)}
              </span>
              <span className="relative whitespace-nowrap text-right" style={{ color: "var(--ink-4)" }}>
                {formatCores(organization.cpuCores ?? 0)} cores
              </span>
            </button>
          );

          return isNoLiveAgent ? (
            <Tooltip key="no-live-agent">
              <TooltipTrigger asChild>{row}</TooltipTrigger>
              <TooltipContent className="max-w-64 text-balance">{NO_LIVE_AGENT_HINT}</TooltipContent>
            </Tooltip>
          ) : (
            <Fragment key={id}>{row}</Fragment>
          );
        })}
      </div>
      {hiddenCount > 0 && (
        <p
          className="m-0 mt-2 px-2 text-[12.5px]"
          style={{ color: "var(--ink-4)" }}
          data-testid="organizations-by-usage-note"
        >
          Showing the top {TOP_COUNT} of {named.length} organizations. Use the organization filter
          to see another.
        </p>
      )}
    </div>
  );
}
