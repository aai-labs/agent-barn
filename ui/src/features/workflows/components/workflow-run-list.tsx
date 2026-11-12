"use client";

import { type ReactNode } from "react";

import { AppErrorState } from "@/components/app-error-state";
import { AgentAvatar } from "@/features/agents/components/agent-avatar";

import {
  useWorkflowRuns,
  type WorkflowRunFilters,
} from "../hooks/use-workflow-runs";
import {
  isRunTerminal,
  pendingApproval,
  runStateLabel,
  runTitle,
  type WorkflowRun,
} from "../run-schemas";
import { WorkflowPager } from "./workflow-pager";
import { StatusBadge, runTone } from "./workflow-run-parts";

function currentStep(run: WorkflowRun): string {
  const step = run.steps[run.nextStep];
  if (!step || isRunTerminal(run.state))
    return `${Math.min(run.nextStep, run.steps.length)} of ${run.steps.length} steps`;
  return `Step ${run.nextStep + 1} of ${run.steps.length} · ${step.name}`;
}

/** How long a run took, or has been going: `54m`, `1h 46m`, `3d 2h`. */
export function runDuration(run: WorkflowRun, now = Date.now()): string {
  const end = run.settledAt ? Date.parse(run.settledAt) : now;
  const minutes = Math.max(0, Math.round((end - Date.parse(run.createdAt)) / 60_000));
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  return hours < 24
    ? `${hours}h ${minutes % 60}m`
    : `${Math.floor(hours / 24)}d ${hours % 24}h`;
}

/** The Agent running a run. A deleted Agent keeps its name, with a tag and no link. */
export function RunAgent({ run }: { run: WorkflowRun }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-1.5">
      <AgentAvatar agent={{ id: run.agentId, name: run.agentName }} size="xs" />
      <span className="truncate">{run.agentName}</span>
      {run.agentArchived && (
        <span className="shrink-0 rounded-full bg-[var(--bg-soft)] px-2 py-0.5 text-[11px] font-medium text-[var(--ink-3)]">
          Archived
        </span>
      )}
    </span>
  );
}

/**
 * A section of runs across the Agents the viewer can read, newest first. `showAgent`
 * names each run's Agent, for lists that span several.
 */
export function WorkflowRunList({
  title,
  filters,
  page,
  onPageChange,
  onOpen,
  showAgent = true,
  empty = null,
}: {
  title: string;
  filters: WorkflowRunFilters;
  page: number;
  onPageChange?: (page: number) => void;
  onOpen: (run: WorkflowRun) => void;
  showAgent?: boolean;
  /** Shown in place of the section when it has no runs at all. */
  empty?: ReactNode;
}) {
  const runs = useWorkflowRuns(filters, page);
  if (runs.error)
    return (
      <AppErrorState
        error={runs.error}
        title="Couldn’t load runs"
        onRetry={() => void runs.refetch()}
      />
    );
  if (!runs.data) return <p role="status">Loading runs…</p>;
  if (runs.data.total === 0) return <>{empty}</>;
  return (
    <section aria-label={title} className="mb-6">
      <h2 className="mb-3 text-[13px] font-semibold text-[var(--ink-3)]">{title}</h2>
      <ul className="overflow-hidden rounded-2xl border border-[var(--line)] bg-[var(--bg-elev)]">
        {runs.data.items.map((run) => {
          const waiting = pendingApproval(run);
          return (
            <li key={run.id} className="border-b border-[var(--line)] last:border-0">
              <button
                type="button"
                onClick={() => onOpen(run)}
                className="af-hover-bg grid w-full grid-cols-1 items-center gap-2 px-6 py-4 text-left sm:grid-cols-[minmax(0,1fr)_minmax(0,220px)_160px_130px] sm:gap-4"
              >
                <span className="min-w-0">
                  <span className="block truncate text-sm font-semibold">
                    {runTitle(run)}
                    {run.rerunOfRunId && (
                      <span className="font-normal text-[var(--ink-3)]"> · Re-run</span>
                    )}
                  </span>
                  <span className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-[var(--ink-3)]">
                    {showAgent && <RunAgent run={run} />}
                    {showAgent && <span aria-hidden="true">·</span>}
                    <span className="truncate">{run.name}</span>
                  </span>
                </span>
                <span className="min-w-0">
                  <span className="block text-[11px] font-semibold uppercase tracking-widest text-[var(--ink-4)]">
                    Current step
                  </span>
                  <span className="block truncate text-xs text-[var(--ink-2)]">
                    {currentStep(run)}
                  </span>
                </span>
                <span>
                  <StatusBadge tone={waiting ? "warn" : runTone(run.state)}>
                    {waiting ? "Waiting on you" : runStateLabel(run.state)}
                  </StatusBadge>
                </span>
                <span className="text-xs text-[var(--ink-3)] sm:text-right">
                  <span className="block">
                    {new Date(run.createdAt).toLocaleString([], {
                      dateStyle: "medium",
                      timeStyle: "short",
                    })}
                  </span>
                  <span className="block tabular-nums">{runDuration(run)}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      {onPageChange && (
        <WorkflowPager
          page={page}
          pageSize={runs.data.pageSize}
          total={runs.data.total}
          onChange={onPageChange}
          noun="runs"
        />
      )}
    </section>
  );
}
