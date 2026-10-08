"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { StatusLine } from "@/features/agents/components/status-line";
import type { AgentHealth } from "@/features/agents/schemas";
import { formatModelName } from "@/features/agents/utils";
import { formatPercent } from "@/features/costs/format";

import { formatBytes, formatCores } from "../format";
import type { AgentResourceUsage } from "../schemas";
import { THROTTLING_WARN_RATIO, usageRatio } from "../utils";
import { LimitLabel } from "./limit-label";
import { MemoryChart } from "./resource-usage-charts";
import { noticeFor } from "./resource-usage-notice";
import { UsageMeter } from "./usage-meter";

/**
 * The panels an opened Agent row shows, as the Organization Usage page and the Platform
 * Resource Usage page both draw them.
 *
 * Presentational only: each page reads its own data, through the endpoints its viewer is
 * allowed to call, and hands the result in. So the two cannot drift apart in how they look,
 * and neither has to know how the other gets its figures.
 */

export const PANEL_GRID_STYLE = { gridTemplateColumns: "repeat(auto-fit, minmax(min(260px, 100%), 1fr))" };

export function Panel({
  title,
  href,
  linkLabel,
  testId,
  children,
}: {
  title: string;
  /** Omit both to draw no link, for a viewer who cannot open the Agent's own pages. */
  href?: string;
  linkLabel?: string;
  testId: string;
  children: ReactNode;
}) {
  return (
    <section className="af-card flex flex-col gap-3 p-4" data-testid={testId} aria-label={title}>
      <h3 className="m-0 text-[13px] font-semibold uppercase tracking-[0.06em]" style={{ color: "var(--ink-4)" }}>
        {title}
      </h3>
      <div className="flex-1">{children}</div>
      {href && linkLabel && (
        <Link
          href={href}
          className="text-[13px] font-medium underline-offset-2 hover:underline"
          style={{ color: "var(--ink-2)" }}
        >
          {linkLabel} →
        </Link>
      )}
    </section>
  );
}

export function Muted({ children }: { children: ReactNode }) {
  return (
    <p className="m-0 text-[13px] leading-relaxed" style={{ color: "var(--ink-3)" }}>
      {children}
    </p>
  );
}

export function Fact({ label, value, mono }: { label: string; value: ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3 text-[13px]">
      <span style={{ color: "var(--ink-4)" }}>{label}</span>
      <span className={`truncate text-right ${mono ? "font-mono" : ""}`} style={{ color: "var(--ink-2)" }}>
        {value}
      </span>
    </div>
  );
}

export function PanelSkeleton() {
  return (
    <div className="flex flex-col gap-2" data-testid="agent-overview-panel-skeleton">
      <Skeleton className="h-6 w-24" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-4/5" />
    </div>
  );
}

export interface StatusFactsProps {
  status: "RUNNING" | "STOPPED" | "ERROR";
  health: AgentHealth | null;
  /** False when the viewer may not read health, so a running Agent is only known to be running. */
  canReadHealth: boolean;
  /** The classified failure of an Agent in ERROR. */
  lastErrorSummary: string | null;
  effectiveModel: string;
  agentType: string;
  createdAt: string;
  /** Null when the cluster has not been asked, or could not be. */
  restartCount: number | null;
  terminationReason: string | null;
}

export function StatusFacts({
  status,
  health,
  canReadHealth,
  lastErrorSummary,
  effectiveModel,
  agentType,
  createdAt,
  restartCount,
  terminationReason,
}: StatusFactsProps) {
  return (
    <div className="flex flex-col gap-2">
      <div className="mb-1">
        {status === "RUNNING" && !canReadHealth ? (
          <span className="text-[12.5px]" style={{ color: "var(--ink-3)" }}>
            Running
          </span>
        ) : (
          <StatusLine status={status} health={health} />
        )}
      </div>
      {lastErrorSummary && (
        <p className="m-0 text-[13px] leading-relaxed" style={{ color: "var(--err)" }}>
          {lastErrorSummary}
        </p>
      )}
      <Fact label="Model" value={formatModelName(effectiveModel) || "—"} mono />
      <Fact label="Runtime" value={agentType} />
      <Fact label="Created" value={new Date(createdAt).toLocaleDateString()} />
      {restartCount !== null && (
        <>
          <Fact label="Restarts" value={restartCount} />
          {terminationReason && <Fact label="Last stopped by" value={terminationReason} />}
        </>
      )}
    </div>
  );
}

/** The figures one Agent's usage panel draws; an Agent's id is the caller's business. */
export type UsageFigures = Omit<AgentResourceUsage, "agentId">;

export interface UsageFactsProps {
  /** False when the viewer may not read this Agent's usage. */
  canRead: boolean;
  stopped: boolean;
  isLoading: boolean;
  failed: boolean;
  usage: UsageFigures | null;
}

export function UsageFacts({ canRead, stopped, isLoading, failed, usage }: UsageFactsProps) {
  if (!canRead) return <Muted>You don&apos;t have access to this agent&apos;s resource usage.</Muted>;
  if (stopped) return <Muted>Stopped. Usage is recorded while the agent runs.</Muted>;
  if (isLoading) return <PanelSkeleton />;
  if (failed || !usage) return <Muted>Resource usage couldn&apos;t be loaded.</Muted>;

  const notice = noticeFor(usage.availability, usage.state);
  if (notice) {
    return (
      <div className="flex flex-col gap-1">
        <p className="m-0 text-[13px] font-medium" style={{ color: "var(--ink-2)" }}>
          {notice.title}
        </p>
        <Muted>{notice.body}</Muted>
      </div>
    );
  }

  const memoryRatio = usageRatio(usage.memoryWorkingSetBytes, usage.memoryLimitBytes);
  const cpuRatio = usageRatio(usage.cpuCores, usage.cpuLimitCores);
  const throttled = usage.cpuThrottledRatio;

  return (
    <div className="flex flex-col gap-3">
      <MeterFact
        label="Memory"
        text={
          usage.memoryWorkingSetBytes !== null ? (
            <>
              {formatBytes(usage.memoryWorkingSetBytes)}
              {usage.memoryLimitBytes !== null && (
                <>
                  {` of ${formatBytes(usage.memoryLimitBytes)}`}
                  <LimitLabel />
                </>
              )}
            </>
          ) : (
            "—"
          )
        }
        ratio={memoryRatio}
        markerRatio={usageRatio(usage.memoryRequestBytes, usage.memoryLimitBytes)}
        requestText={usage.memoryRequestBytes !== null ? `requests ${formatBytes(usage.memoryRequestBytes)}` : null}
        testId="usage-panel-memory-request"
      />
      <MeterFact
        label="CPU"
        text={
          usage.cpuCores !== null ? (
            <>
              {`${formatCores(usage.cpuCores)}${
                usage.cpuLimitCores !== null ? ` of ${formatCores(usage.cpuLimitCores)}` : ""
              } cores`}
              {usage.cpuLimitCores !== null && <LimitLabel />}
            </>
          ) : (
            "—"
          )
        }
        ratio={cpuRatio}
        markerRatio={usageRatio(usage.cpuRequestCores, usage.cpuLimitCores)}
        requestText={usage.cpuRequestCores !== null ? `requests ${formatCores(usage.cpuRequestCores)} cores` : null}
        testId="usage-panel-cpu-request"
      />
      <div>
        <Fact label="Peak memory, 24h" value={usage.memoryPeakBytes !== null ? formatBytes(usage.memoryPeakBytes) : "—"} />
        <Fact
          label="CPU throttled, 24h"
          value={
            <span style={{ color: throttled !== null && throttled >= THROTTLING_WARN_RATIO ? "var(--warn)" : undefined }}>
              {throttled !== null ? formatPercent(throttled) : "—"}
            </span>
          }
        />
      </div>
      <MemoryChart
        series={usage.series}
        range={usage.range}
        limitBytes={usage.memoryLimitBytes}
        requestBytes={usage.memoryRequestBytes}
        compact
      />
    </div>
  );
}

function MeterFact({
  label,
  text,
  ratio,
  markerRatio,
  requestText,
  testId,
}: {
  label: string;
  text: ReactNode;
  ratio: number | null;
  /** Where the request sits on the same scale as the limit. */
  markerRatio: number | null;
  requestText: string | null;
  testId: string;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between gap-3 text-[13px]">
        <span style={{ color: "var(--ink-4)" }}>{label}</span>
        <span style={{ color: "var(--ink-2)" }}>{text}</span>
      </div>
      <UsageMeter ratio={ratio} markerRatio={markerRatio} label={`${label} use against its limit`} />
      {requestText && (
        <span className="text-right text-[12px]" style={{ color: "var(--ink-4)" }} data-testid={testId}>
          {requestText}
        </span>
      )}
    </div>
  );
}
