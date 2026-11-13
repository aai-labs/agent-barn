import type { CSSProperties, ReactNode } from "react";
import Link from "next/link";
import { AgentAvatar } from "@/features/agents/components/agent-avatar";
import { Hourglass, Pause } from "lucide-react";
import type { WorkflowApproval, WorkflowRun } from "../run-schemas";
import { runStateLabel } from "../run-schemas";

type Tone = "accent" | "ok" | "warn" | "err" | "muted";

export const toneStyle: Record<Tone, CSSProperties> = {
  accent: { background: "var(--accent-soft)", color: "var(--accent-ink)" },
  ok: { background: "var(--ok-soft)", color: "var(--ok)" },
  warn: { background: "var(--warn-soft)", color: "var(--warn)" },
  err: { background: "var(--err-soft)", color: "var(--err)" },
  muted: { background: "var(--bg-soft)", color: "var(--ink-3)" },
};

export const runTone = (state: WorkflowRun["state"]): Tone =>
  ({
    QUEUED: "muted",
    RUNNING: "accent",
    PAUSED: "warn",
    BLOCKED: "warn",
    AWAITING_APPROVAL: "warn",
    CANCELLING: "warn",
    CANCELLED: "muted",
    SUCCEEDED: "ok",
    FAILED: "err",
  })[state] as Tone;

export function StatusBadge({
  tone,
  children,
}: {
  tone: Tone;
  children: ReactNode;
}) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-semibold"
      style={toneStyle[tone]}
    >
      {children}
    </span>
  );
}

export function RunStatusBadge({
  state,
  approval,
}: {
  state: WorkflowRun["state"];
  /** A request awaiting a decision outranks the run state: the run is waiting on a person. */
  approval?: WorkflowApproval | null;
}) {
  if (approval)
    return (
      <span role="status">
        <StatusBadge tone="warn">
          {approval.state === "LIVE" ? (
            <Hourglass size={13} aria-hidden />
          ) : (
            <Pause size={13} aria-hidden />
          )}
          {approval.state === "LIVE" ? "Waiting on you" : "Awaiting approval · paused"}
        </StatusBadge>
      </span>
    );
  const prefix = state === "RUNNING" ? "● " : state === "SUCCEEDED" ? "✓ " : "";
  return (
    <span role="status">
      <StatusBadge tone={runTone(state)}>
        {prefix}
        {runStateLabel(state)}
      </StatusBadge>
    </span>
  );
}

/** Shared page header for the start, run and output screens of the run design. */
export function RunPageHeader({
  eyebrow,
  title,
  badge,
  agent,
  detail,
  agentHref,
  agentArchived = false,
  actions,
}: {
  eyebrow: string;
  title: string;
  badge: ReactNode;
  agent: { id: string; name: string };
  detail?: string;
  /** Absent for a deleted Agent, which has no page to open. */
  agentHref?: string;
  agentArchived?: boolean;
  actions?: ReactNode;
}) {
  return (
    <header className="mb-8 mt-6 flex flex-wrap items-start justify-between gap-4">
      <div className="space-y-2">
        <p className="text-sm text-[var(--ink-4)]">{eyebrow}</p>
        <h3 className="text-3xl font-semibold tracking-tight">{title}</h3>
        <div className="flex flex-wrap items-center gap-3 text-sm text-[var(--ink-3)]">
          {badge}
          <AgentAvatar agent={agent} size="xs" />
          <span>
            {agent.name}
            {agentArchived && (
              <span className="ml-2 rounded-full bg-[var(--bg-soft)] px-2 py-0.5 text-xs font-medium">
                Archived
              </span>
            )}
            {detail ? ` · ${detail}` : ""}
          </span>
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        {agentHref && (
          <Link className="af-btn" href={agentHref}>
            ↗ Open {agent.name}
          </Link>
        )}
        {actions}
      </div>
    </header>
  );
}

export function RunCard({
  title,
  label,
  children,
  className = "",
  embedded = false,
}: {
  title?: string;
  label?: string;
  children: ReactNode;
  className?: string;
  embedded?: boolean;
}) {
  return (
    <section
      aria-label={label}
      className={`${embedded ? "px-6 py-5" : "rounded-2xl border border-[var(--line)] bg-[var(--bg-elev)] p-6"} ${className}`}
    >
      {title && <h4 className="mb-4 text-lg font-semibold">{title}</h4>}
      {children}
    </section>
  );
}

export function RunRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-[var(--line)] py-3 text-sm">
      <span className="text-[var(--ink-3)]">{label}</span>
      <span className="font-medium text-right">{value}</span>
    </div>
  );
}

/** Bridges the selected navigation card to its detail panel on desktop. */
export function RunViewConnector() {
  return (
    <span
      aria-hidden="true"
      data-testid="run-view-connector"
      className="pointer-events-none absolute -right-8 top-1/2 z-30 hidden h-px w-8 -translate-y-1/2 bg-gradient-to-r from-[var(--line-strong)] to-[var(--ok)] md:block"
    >
      <span className="absolute -right-[3px] top-1/2 size-1.5 -translate-y-1/2 rounded-full bg-[var(--ok)] ring-4 ring-[var(--bg-elev)]" />
    </span>
  );
}

const stepLabel = {
  COMPLETED: "Completed",
  RUNNING: "In progress",
  PENDING: "Not started",
} as const;

/** Vertical timeline of the pinned version's steps, as in the run design. */
export function StepRail({
  steps,
  runState,
  selectedStepId,
  onSelectStep,
  attempt,
  approvals = [],
  pending = null,
}: {
  steps: WorkflowRun["steps"];
  runState: WorkflowRun["state"];
  selectedStepId?: string | null;
  onSelectStep?: (stepId: string) => void;
  attempt?: WorkflowRun["attempt"];
  approvals?: WorkflowApproval[];
  pending?: WorkflowApproval | null;
}) {
  const stopped = runState === "CANCELLED" || runState === "FAILED";
  return (
    <div>
      <h4 className="mb-4 text-[11px] font-semibold uppercase tracking-widest text-[var(--ink-3)]">
        Steps
      </h4>
      <ol aria-label="Step progress" className="relative">
        {steps.map((step, index) => {
          const interrupted = stopped && step.state === "RUNNING";
          const waiting = pending?.stepIndex === index;
          const decided = approvals.filter(
            (item) =>
              item.stepIndex === index &&
              ["RELEASED", "APPROVED", "DECLINED"].includes(item.state),
          );
          const approved = decided.filter((item) => item.state !== "DECLINED").length;
          const declined = decided.length - approved;
          const circle: CSSProperties =
            waiting
              ? { background: "var(--warn)", color: "#fff", boxShadow: "0 0 0 4px var(--warn-soft)" }
              : step.state === "COMPLETED"
              ? { background: "var(--ok)", color: "#fff" }
              : step.state === "RUNNING"
                ? {
                    background: interrupted ? "var(--err)" : "var(--warn)",
                    color: "#fff",
                  }
                : {
                    background: "var(--bg-elev)",
                    color: "var(--ink-4)",
                    border: "1px solid var(--line-strong)",
                  };
          const content = (
            <>
              <span
                data-testid="step-marker"
                className="relative z-20 flex size-8 shrink-0"
              >
                {step.state === "RUNNING" && !interrupted && !waiting && (
                  <span
                    aria-hidden="true"
                    className="absolute inset-0 rounded-full opacity-60 animate-ping motion-reduce:animate-none"
                    style={{ background: "var(--warn)" }}
                  />
                )}
                <span
                  aria-hidden="true"
                  className="relative flex size-8 items-center justify-center rounded-full text-sm font-semibold"
                  style={circle}
                >
                  {waiting ? (
                    pending?.state === "LIVE" ? (
                      <Hourglass size={14} />
                    ) : (
                      <Pause size={14} />
                    )
                  ) : (
                    index + 1
                  )}
                </span>
              </span>
              <div className="min-w-0 pt-1">
                <p className="text-sm font-semibold">{step.name}</p>
                <p className="mt-1 text-xs text-[var(--ink-3)]">
                  <span className="sr-only">Step {index + 1}: </span>
                  {waiting && pending?.state === "PARKED"
                    ? "Session paused"
                    : interrupted
                    ? "Needs attention"
                    : step.state === "RUNNING" && attempt
                      ? `${stepLabel[step.state]} · attempt ${attempt.number}`
                      : stepLabel[step.state]}
                </p>
                {(waiting || decided.length > 0) && (
                  <p className="mt-1.5 flex flex-wrap gap-1">
                    {waiting && (
                      <span
                        className="rounded-md px-2 py-0.5 text-[11px] font-semibold"
                        style={{ background: "var(--warn-soft)", color: "var(--warn)" }}
                      >
                        Waiting on you
                      </span>
                    )}
                    {approved > 0 && (
                      <span className="rounded-md bg-[var(--bg-soft)] px-2 py-0.5 text-[11px] font-semibold text-[var(--ink-2)]">
                        {approved} approved
                      </span>
                    )}
                    {declined > 0 && (
                      <span className="rounded-md bg-[var(--bg-soft)] px-2 py-0.5 text-[11px] font-semibold text-[var(--ink-2)]">
                        {declined} declined
                      </span>
                    )}
                  </p>
                )}
              </div>
            </>
          );
          return (
            <li key={step.id} className="relative pb-3 last:pb-0">
              {index < steps.length - 1 && (
                <span
                  aria-hidden="true"
                  data-testid="step-connector"
                  className="pointer-events-none absolute z-10 w-px -translate-x-1/2 bg-[var(--line-strong)]"
                  style={{
                    left: onSelectStep ? 24 : 16,
                    top: onSelectStep ? 40 : 32,
                    bottom: onSelectStep ? -8 : 0,
                  }}
                />
              )}
              {onSelectStep ? (
                <button
                  type="button"
                  aria-label={`Step ${index + 1}: ${step.name}`}
                  aria-current={selectedStepId === step.id ? "step" : undefined}
                  aria-controls="workflow-run-panel"
                  onClick={() => onSelectStep(step.id)}
                  className={`relative flex w-full gap-3 rounded-xl p-2 text-left focus-visible:outline-2 focus-visible:outline-offset-2 ${selectedStepId === step.id ? "bg-[var(--bg-soft)] ring-1 ring-[var(--line-strong)]" : "hover:bg-[var(--bg-soft)]"}`}
                >
                  {content}
                  {selectedStepId === step.id && <RunViewConnector />}
                </button>
              ) : (
                <div className="relative flex gap-3 pb-5">{content}</div>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
