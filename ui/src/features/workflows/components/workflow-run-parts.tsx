import type { CSSProperties, ReactNode } from "react";
import Link from "next/link";
import { AgentAvatar } from "@/features/agents/components/agent-avatar";
import type { WorkflowRun } from "../run-schemas";
import { runStateLabel } from "../run-schemas";

type Tone = "ok" | "warn" | "err" | "muted";

const toneStyle: Record<Tone, CSSProperties> = {
  ok: { background: "var(--ok-soft)", color: "var(--ok)" },
  warn: { background: "var(--warn-soft)", color: "var(--warn)" },
  err: { background: "var(--err-soft)", color: "var(--err)" },
  muted: { background: "var(--bg-soft)", color: "var(--ink-3)" },
};

export const runTone = (state: WorkflowRun["state"]): Tone =>
  ({
    QUEUED: "muted",
    RUNNING: "ok",
    PAUSED: "warn",
    BLOCKED: "warn",
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

export function RunStatusBadge({ state }: { state: WorkflowRun["state"] }) {
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
  actions,
}: {
  eyebrow: string;
  title: string;
  badge: ReactNode;
  agent: { id: string; name: string };
  detail?: string;
  agentHref?: string;
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
}: {
  title?: string;
  label?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      aria-label={label}
      className={`rounded-2xl border border-[var(--line)] bg-[var(--bg-elev)] p-6 ${className}`}
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
}: {
  steps: WorkflowRun["steps"];
  runState: WorkflowRun["state"];
  selectedStepId?: string | null;
  onSelectStep?: (stepId: string) => void;
  attempt?: WorkflowRun["attempt"];
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
          const circle: CSSProperties =
            step.state === "COMPLETED"
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
                {step.state === "RUNNING" && !interrupted && (
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
                  {index + 1}
                </span>
              </span>
              <div className="min-w-0 pt-1">
                <p className="text-sm font-semibold">{step.name}</p>
                <p className="mt-1 text-xs text-[var(--ink-3)]">
                  <span className="sr-only">Step {index + 1}: </span>
                  {interrupted
                    ? "Needs attention"
                    : step.state === "RUNNING" && attempt
                      ? `${stepLabel[step.state]} · attempt ${attempt.number} of ${attempt.limit}`
                      : stepLabel[step.state]}
                </p>
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
