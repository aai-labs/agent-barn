"use client";

import { PlayCircle } from "lucide-react";
import { AppErrorState } from "@/components/app-error-state";
import { useAgentRuns } from "../hooks/use-workflow-runs";
import { pendingApproval, runStateLabel, type WorkflowRun } from "../run-schemas";
import { StatusBadge, runTone } from "./workflow-run-parts";
import { WorkflowPager } from "./workflow-pager";

function currentStep(run: WorkflowRun): string {
  const step = run.steps[run.nextStep];
  if (!step || ["SUCCEEDED", "CANCELLED", "FAILED"].includes(run.state))
    return `${Math.min(run.nextStep, run.steps.length)} of ${run.steps.length} steps`;
  return `Step ${run.nextStep + 1} of ${run.steps.length} · ${step.name}`;
}

/** Recent runs across every workflow of this Agent; a run waiting on a person says so. */
export function WorkflowAgentRuns({
  agentId,
  page,
  onPageChange,
  onOpen,
  onShowWorkflows,
}: {
  agentId: string;
  page: number;
  onPageChange: (page: number) => void;
  onOpen: (run: { id: string; workflowId: string }) => void;
  onShowWorkflows: () => void;
}) {
  const runs = useAgentRuns(agentId, page);
  if (runs.error)
    return (
      <AppErrorState
        error={runs.error}
        title="Couldn’t load runs"
        onRetry={() => void runs.refetch()}
      />
    );
  if (!runs.data) return <p role="status">Loading runs…</p>;
  if (runs.data.total === 0)
    return (
      <div className="flex flex-col items-center pt-16 pb-12 text-center">
        <span className="mb-4 flex size-14 items-center justify-center rounded-2xl bg-[var(--bg-soft)] text-[var(--ink-3)]">
          <PlayCircle aria-hidden="true" size={24} />
        </span>
        <h2 className="text-lg font-semibold">No runs yet</h2>
        <p className="mt-2 max-w-sm text-sm text-[var(--ink-3)]">
          Runs appear here once you start one from a{" "}
          <button type="button" className="underline hover:text-[var(--ink)]" onClick={onShowWorkflows}>
            saved workflow
          </button>
          .
        </p>
      </div>
    );
  return (
    <section aria-label="Recent runs">
      <h2 className="mb-3 text-[13px] font-semibold text-[var(--ink-3)]">Recent runs</h2>
      <ul className="overflow-hidden rounded-2xl border border-[var(--line)] bg-[var(--bg-elev)]">
        {runs.data.items.map((run) => {
          const waiting = pendingApproval(run);
          return (
            <li key={run.id} className="border-b border-[var(--line)] last:border-0">
              <button
                type="button"
                onClick={() => onOpen({ id: run.id, workflowId: run.workflowId })}
                className="af-hover-bg grid w-full grid-cols-1 items-center gap-2 px-6 py-4 text-left sm:grid-cols-[minmax(0,1fr)_minmax(0,220px)_160px_130px] sm:gap-4"
              >
                <span className="min-w-0 truncate text-sm font-semibold">
                  {run.name}
                  {run.rerunOfRunId && (
                    <span className="font-normal text-[var(--ink-3)]"> · Re-run</span>
                  )}
                </span>
                <span className="truncate text-xs text-[var(--ink-3)]">{currentStep(run)}</span>
                <span>
                  <StatusBadge tone={waiting ? "warn" : runTone(run.state)}>
                    {waiting ? "Waiting on you" : runStateLabel(run.state)}
                  </StatusBadge>
                </span>
                <span className="text-xs text-[var(--ink-3)]">
                  {new Date(run.createdAt).toLocaleString([], {
                    dateStyle: "medium",
                    timeStyle: "short",
                  })}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      <WorkflowPager
        page={page}
        pageSize={runs.data.pageSize}
        total={runs.data.total}
        onChange={onPageChange}
        noun="runs"
      />
    </section>
  );
}
