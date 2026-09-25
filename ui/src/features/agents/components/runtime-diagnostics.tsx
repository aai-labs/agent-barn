"use client";

import type { ReactNode } from "react";
import Link from "next/link";

import { AppErrorState } from "@/components/app-error-state";

import { useAgentRuntimeDiagnostics } from "../hooks/use-agent-runtime-diagnostics";
import type { Agent } from "../schemas";

function timestamp(value: string | null) {
  return value
    ? new Date(value).toISOString().slice(0, 19).replace("T", " ") + " UTC"
    : "Not recorded";
}

export function RuntimeDiagnostics({ agent, lastCallAt, orgId, usageAvailable }: {
  agent: Agent;
  usageAvailable: boolean;
  lastCallAt: string | null;
  orgId: string | null;
}) {
  const query = useAgentRuntimeDiagnostics(agent.id);
  const data = query.data;
  return (
    <section className="af-card flex flex-col gap-5 p-5" data-testid="agent-runtime-diagnostics" aria-label="Runtime diagnostics">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1 basis-64">
          <h2 className="m-0 text-[14px] font-semibold" style={{ color: "var(--ink)" }}>Runtime diagnostics</h2>
          <p className="m-0 mt-1 text-[12px] leading-relaxed" style={{ color: "var(--ink-4)" }}>
            Current runtime evidence, independent of the usage date range.
          </p>
        </div>
        <button className="af-btn af-btn-sm shrink-0" disabled={query.isFetching} onClick={() => void query.refetch()}>
          Refresh diagnostics
        </button>
      </div>

      <dl className="m-0 grid gap-x-6 gap-y-4 sm:grid-cols-2 lg:grid-cols-3">
        <DiagnosticField label="Agent state">{agent.status === "STOPPED" ? "Stopped" : agent.status === "RUNNING" ? "Running" : "Error"}</DiagnosticField>
        <DiagnosticField label="Last observation">{data ? timestamp(data.observedAt) : "Not available"}</DiagnosticField>
        <DiagnosticField label="Last model call in selected range">{usageAvailable ? timestamp(lastCallAt) : "Usage unavailable"}</DiagnosticField>
      </dl>

      {query.isPending ? <p className="m-0 text-[13px]">Loading runtime evidence...</p> : query.error ? (
        <AppErrorState error={query.error} title="Runtime diagnostics unavailable"
          description="Usage remains available. Retry to inspect the runtime."
          onRetry={() => void query.refetch()} retryLabel="Retry diagnostics" className="min-h-0 p-0" />
      ) : data && <>
        {agent.lastError && <div className="rounded-lg p-3 text-[13px] leading-relaxed" style={{ background: "var(--err-soft)", color: "var(--err)" }} role="status">
          <p className="m-0 font-medium">{agent.lastError.summary}</p>
          {agent.lastError.detail && <p className="m-0 mt-1">{agent.lastError.detail}</p>}
        </div>}
        {!data.available ? (
          <div className="rounded-lg px-4 py-3.5" style={{ background: "var(--bg-soft)", border: "1px solid var(--line)" }}>
            <p className="m-0 text-[13px] font-medium" style={{ color: "var(--ink-2)" }}>No current runtime evidence</p>
            <p className="m-0 mt-1 text-[12px] leading-relaxed" style={{ color: "var(--ink-4)" }}>Check Logs for retained sessions.</p>
          </div>
        ) : <>
          <dl className="m-0 grid gap-x-6 gap-y-4 border-t pt-4 sm:grid-cols-2 lg:grid-cols-3" style={{ borderColor: "var(--line)" }}>
            <DiagnosticField label="Container">{data.waitingReason ?? (data.ready ? "Ready" : "Not ready")}</DiagnosticField>
            <DiagnosticField label="Restarts in this pod">{data.restartCount}</DiagnosticField>
            <DiagnosticField label="Pod created">{timestamp(data.podCreatedAt)}</DiagnosticField>
            <DiagnosticField label="Last termination">{data.terminationReason ?? "Not recorded"}
              {data.exitCode !== null && ` (exit ${data.exitCode})`}</DiagnosticField>
            <DiagnosticField label="Termination time">{timestamp(data.finishedAt)}</DiagnosticField>
          </dl>
          <div className="flex flex-col gap-3">
            <LogEvidence title="Previous container logs" available={data.previousLogsAvailable} lines={data.previousLogs} />
            <LogEvidence title="Current container logs" available={data.currentLogsAvailable} lines={data.currentLogs} />
          </div>
        </>}
      </>}

      <div className="flex flex-col gap-3 border-t pt-4" style={{ borderColor: "var(--line)" }}>
        <div className="flex max-w-[85ch] flex-col gap-2 text-[12px] leading-relaxed" style={{ color: "var(--ink-4)" }}>
          <p className="m-0">Historical spend does not establish a crash cause. Usage can arrive late; the last recorded call does not prove billing has stopped.</p>
          {data?.available && <p className="m-0">Restart counts reset when a pod is replaced. Termination time is the latest observed exit, not the start of a crash loop. Logs show up to 100 lines per instance and may disappear after replacement.</p>}
        </div>
        {orgId && <Link className="af-btn af-btn-sm self-start" href={`/dashboard/${orgId}/agents/${agent.id}?tab=logs`}>Open Logs and retained sessions</Link>}
      </div>
    </section>
  );
}

function DiagnosticField({ label, children }: { label: string; children: ReactNode }) {
  return <div className="min-w-0">
    <dt className="text-[12px] leading-relaxed" style={{ color: "var(--ink-4)" }}>{label}</dt>
    <dd className="m-0 mt-1 break-words text-[13px] font-medium leading-relaxed tabular-nums" style={{ color: "var(--ink)" }}>{children}</dd>
  </div>;
}

function LogEvidence({ title, available, lines }: { title: string; available: boolean; lines: string[] }) {
  return <details className="overflow-hidden rounded-lg border" style={{ borderColor: "var(--line)" }} open>
    <summary className="cursor-pointer px-4 py-3 text-[13px] font-medium" style={{ background: "var(--bg-soft)" }}>{title}</summary>
    {available ? <pre className="m-0 max-h-64 overflow-auto whitespace-pre-wrap break-all border-t px-4 py-3 text-[12px] leading-relaxed"
      style={{ borderColor: "var(--line)" }}>{lines.join("\n") || "No log lines returned."}</pre>
      : <p className="m-0 px-4 py-3 text-[12px] leading-relaxed" style={{ color: "var(--ink-4)" }}>Logs unavailable for this container instance.</p>}
  </details>;
}
