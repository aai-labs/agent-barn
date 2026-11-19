"use client";

import {
  AlertTriangle,
  CheckCircle2,
  CircleSlash,
  Clock,
  Hourglass,
  type LucideIcon,
  Pause,
  XCircle,
  Zap,
} from "lucide-react";
import { type ReactNode } from "react";

import { AppErrorState } from "@/components/app-error-state";
import { AgentAvatar } from "@/features/agents/components/agent-avatar";

import {
  useWorkflowRuns,
  type WorkflowRunFilters,
} from "../hooks/use-workflow-runs";
import {
  pendingApproval,
  runStateLabel,
  runTitle,
  type WorkflowRun,
} from "../run-schemas";
import { WorkflowPager } from "./workflow-pager";
import { runTone, toneStyle } from "./workflow-run-parts";

/** The step a run is on, or the one it ended on: `Review each PR`. */
function currentStep(run: WorkflowRun): string {
  const index = Math.min(run.nextStep, run.steps.length - 1);
  return run.steps[index]?.name ?? "—";
}

const stateIcon: Record<WorkflowRun["state"], LucideIcon> = {
  QUEUED: Clock,
  RUNNING: Zap,
  PAUSED: Pause,
  BLOCKED: AlertTriangle,
  AWAITING_APPROVAL: Hourglass,
  CANCELLING: CircleSlash,
  CANCELLED: CircleSlash,
  SUCCEEDED: CheckCircle2,
  FAILED: XCircle,
};

/** A run's state as a fixed-width pill; a request awaiting a decision outranks it. */
function RunStatePill({ run }: { run: WorkflowRun }) {
  const waiting = pendingApproval(run) !== null;
  const Icon = waiting ? Hourglass : stateIcon[run.state];
  return (
    <span
      className="inline-flex w-full max-w-[150px] items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold"
      style={toneStyle[waiting ? "warn" : runTone(run.state)]}
    >
      <Icon size={13} aria-hidden="true" className="shrink-0" />
      <span className="truncate">{waiting ? "Waiting on you" : runStateLabel(run.state)}</span>
    </span>
  );
}

/** When a run started: `Today 09:04`, `Yesterday 14:20`, `May 8 16:02`. */
export function runStarted(at: string, now = new Date()): string {
  const date = new Date(at);
  const time = date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const day = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const daysAgo = Math.round((today.getTime() - day.getTime()) / 86_400_000);
  if (daysAgo === 0) return `Today ${time}`;
  if (daysAgo === 1) return `Yesterday ${time}`;
  const sameYear = date.getFullYear() === now.getFullYear();
  return `${date.toLocaleDateString([], {
    month: "short",
    day: "numeric",
    ...(sameYear ? {} : { year: "numeric" }),
  })} ${time}`;
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
export function RunAgent({ run, avatar = true }: { run: WorkflowRun; avatar?: boolean }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-1.5">
      {avatar && <AgentAvatar agent={{ id: run.agentId, name: run.agentName }} size="xs" />}
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
        {runs.data.items.map((run) => (
          <li key={run.id} className="border-b border-[var(--line)] last:border-0">
            <button
              type="button"
              onClick={() => onOpen(run)}
              className={`af-hover-bg grid w-full grid-cols-1 items-center gap-2 px-6 py-4 text-left sm:gap-4 ${
                showAgent
                  ? "sm:grid-cols-[auto_minmax(0,1fr)_minmax(0,200px)_150px_120px]"
                  : "sm:grid-cols-[minmax(0,1fr)_minmax(0,200px)_150px_120px]"
              }`}
            >
              {showAgent && (
                <span className="hidden sm:block">
                  <AgentAvatar agent={{ id: run.agentId, name: run.agentName }} size="sm" />
                </span>
              )}
              <span className="min-w-0">
                <span className="block truncate text-sm font-semibold">
                  {runTitle(run)}
                  {run.rerunOfRunId && (
                    <span className="font-normal text-[var(--ink-3)]"> · Re-run</span>
                  )}
                </span>
                <span className="mt-1 flex min-w-0 items-center gap-x-1.5 text-xs text-[var(--ink-3)]">
                  <span className="shrink-0 font-mono" title={run.id}>
                    {run.id.slice(-6)}
                  </span>
                  {showAgent && <span aria-hidden="true">·</span>}
                  {showAgent && <RunAgent run={run} avatar={false} />}
                  <span aria-hidden="true">·</span>
                  <span className="truncate">{run.name}</span>
                </span>
              </span>
              <span className="min-w-0">
                <span className="block text-[11px] font-semibold uppercase tracking-widest text-[var(--ink-4)]">
                  Current step
                </span>
                <span className="mt-0.5 block truncate text-sm text-[var(--ink-2)]">
                  {currentStep(run)}
                </span>
              </span>
              <span>
                <RunStatePill run={run} />
              </span>
              <span className="text-xs text-[var(--ink-3)] sm:text-right">
                <span className="block">{runStarted(run.createdAt)}</span>
                <span className="block tabular-nums">{runDuration(run)}</span>
              </span>
            </button>
          </li>
        ))}
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
