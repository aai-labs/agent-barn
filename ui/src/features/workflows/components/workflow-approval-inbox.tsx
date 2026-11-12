"use client";

import { Hourglass } from "lucide-react";
import { useAwaitingApprovals } from "../hooks/use-workflow-runs";
import { pendingApproval, runTitle } from "../run-schemas";
import { RunAgent } from "./workflow-run-list";

function waited(since: string): string {
  const minutes = Math.max(0, Math.round((Date.now() - Date.parse(since)) / 60_000));
  return minutes < 60 ? `${minutes}m` : `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

/**
 * Runs waiting on a person's approval, above everything else on a Workflows page: one
 * Agent's on its own page, or every Agent the viewer can read on the Organization's.
 */
export function WorkflowApprovalInbox({
  agentId,
  onOpen,
}: {
  agentId?: string;
  onOpen: (run: { id: string; workflowId: string }) => void;
}) {
  const runs = useAwaitingApprovals(agentId);
  const items = (runs.data?.items ?? []).flatMap((run) => {
    const approval = pendingApproval(run);
    return approval ? [{ run, approval }] : [];
  });
  if (items.length === 0) return null;
  // Viewers see what is waiting, but only those who may decide are told it waits on them.
  const title = items.some(({ run }) => run.allowedActions.includes("decide"))
    ? "Waiting on your approval"
    : "Waiting on approval";
  return (
    <section
      aria-label={title}
      className="mb-6 overflow-hidden rounded-2xl border border-[var(--line)] bg-[var(--bg-elev)] shadow-sm"
    >
      <div className="flex items-center justify-between border-b border-[var(--line)] px-6 py-3">
        <h2
          className="flex items-center gap-2 text-sm font-semibold"
          style={{ color: "var(--warn)" }}
        >
          <Hourglass size={15} aria-hidden />
          {title}
        </h2>
        <span className="text-xs text-[var(--ink-3)]">
          {runs.data!.total} {runs.data!.total === 1 ? "run" : "runs"}
        </span>
      </div>
      <ul>
        {items.map(({ run, approval }) => (
          <li
            key={run.id}
            className="flex flex-wrap items-center gap-4 border-b border-[var(--line)] px-6 py-4 last:border-0"
          >
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold">
                {runTitle(run)}
                <span className="font-normal text-[var(--ink-3)]">
                  {" "}
                  · Step {approval.stepIndex + 1}
                  {run.steps[approval.stepIndex] && ` · ${run.steps[approval.stepIndex].name}`}
                </span>
              </p>
              <p className="mt-1 truncate font-mono text-xs text-[var(--ink-2)]">
                {approval.command}
              </p>
              {!agentId && (
                <p className="mt-1 text-xs text-[var(--ink-3)]">
                  <RunAgent run={run} />
                </p>
              )}
            </div>
            {approval.state === "LIVE" ? (
              <span
                className="rounded-md px-2 py-1 text-xs font-semibold"
                style={{ background: "var(--warn-soft)", color: "var(--warn)" }}
              >
                Live · answer by{" "}
                {new Date(approval.liveUntil).toLocaleTimeString([], {
                  hour: "numeric",
                  minute: "2-digit",
                })}
              </span>
            ) : (
              <span className="rounded-md bg-[var(--bg-soft)] px-2 py-1 text-xs font-semibold text-[var(--ink-2)]">
                Paused · {waited(approval.createdAt)}
              </span>
            )}
            <button
              type="button"
              className="af-btn af-btn-primary af-btn-sm"
              onClick={() => onOpen({ id: run.id, workflowId: run.workflowId })}
            >
              Review →
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
