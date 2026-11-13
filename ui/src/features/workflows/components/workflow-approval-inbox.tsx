"use client";

import { Hourglass } from "lucide-react";

import { AgentAvatar } from "@/features/agents/components/agent-avatar";

import { useAwaitingApprovals } from "../hooks/use-workflow-runs";
import { pendingApproval, runTitle } from "../run-schemas";

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
            className="flex items-center gap-4 border-b border-[var(--line)] px-6 py-4 last:border-0"
          >
            <AgentAvatar agent={{ id: run.agentId, name: run.agentName }} size="sm" />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold">{runTitle(run)}</p>
              <p className="mt-1 flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-[var(--ink-3)]">
                <span className="max-w-full truncate font-mono text-[var(--ink-2)]">
                  {approval.command}
                </span>
                <span aria-hidden="true">·</span>
                {approval.state === "LIVE" ? (
                  <span className="font-semibold" style={{ color: "var(--warn)" }}>
                    Live · answer by{" "}
                    {new Date(approval.liveUntil).toLocaleTimeString([], {
                      hour: "numeric",
                      minute: "2-digit",
                    })}
                  </span>
                ) : (
                  <span className="font-semibold">Paused · {waited(approval.createdAt)}</span>
                )}
                {!agentId && <span aria-hidden="true">·</span>}
                {!agentId && <span className="truncate">{run.agentName}</span>}
              </p>
            </div>
            <button
              type="button"
              className="af-btn af-btn-primary af-btn-sm shrink-0"
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
