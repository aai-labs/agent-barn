import { runStateLabel, type WorkflowRun } from "../run-schemas";

function duration(start: string, end: string): string {
  const seconds = Math.max(
    0,
    Math.round((Date.parse(end) - Date.parse(start)) / 1000),
  );
  if (seconds < 1) return "<1s";
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainder = seconds % 60;
  return [
    hours ? `${hours}h` : "",
    minutes ? `${minutes}m` : "",
    remainder ? `${remainder}s` : "",
  ]
    .filter(Boolean)
    .join(" ");
}

export function stepTiming(
  step: WorkflowRun["steps"][number],
  runState: WorkflowRun["state"],
): string {
  if (step.startedAt && step.completedAt)
    return duration(step.startedAt, step.completedAt);
  if (step.state === "COMPLETED") return "Unavailable";
  if (["CANCELLED", "FAILED", "BLOCKED", "PAUSED"].includes(runState))
    return "Not completed";
  return step.startedAt || step.state === "RUNNING"
    ? "In progress"
    : "Not started";
}

export function WorkflowRunTiming({ run }: { run: WorkflowRun }) {
  return (
    <section
      aria-label="Run timing"
      className="min-w-0 rounded-2xl border border-[var(--line)] bg-[var(--bg-elev)] px-6 py-4 md:col-start-2"
    >
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="text-sm font-semibold">Time taken</h4>
        <p className="text-sm tabular-nums text-[var(--ink-3)]">
          {run.settledAt
            ? `Total ${duration(run.createdAt, run.settledAt)}`
            : runStateLabel(run.state)}
        </p>
      </div>
      <dl className="space-y-2">
        {run.steps.map((step, index) => (
          <div
            key={step.id}
            className="flex items-baseline justify-between gap-4 text-sm"
          >
            <dt className="min-w-0 text-[var(--ink-3)]">
              {index + 1}. {step.name}
            </dt>
            <dd className="shrink-0 font-medium tabular-nums">
              {stepTiming(step, run.state)}
            </dd>
          </div>
        ))}
      </dl>
      <p className="mt-3 text-xs text-[var(--ink-3)]">
        Elapsed time includes waiting and retries.
      </p>
    </section>
  );
}
