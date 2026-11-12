import type { CronJob, SourceState } from "../schemas";
import { formatAge, type Tone } from "../utils";
import { EmptyRow, Section, StatusDot } from "./section";

const STATE_TONE: Record<CronJob["state"], Tone> = { failing: "err", stalled: "warn", ok: "ok", suspended: "muted" };

const STATE_TEXT: Record<CronJob["state"], string> = {
  failing: "Last run failed",
  stalled: "No successful run in over a day",
  ok: "Working",
  suspended: "Switched off",
};

function lastWorked(cron: CronJob): string {
  if (cron.lastSuccessfulAt) return `last succeeded ${formatAge(cron.lastSuccessfulAt)}`;
  return "has never succeeded";
}

/** The platform's scheduled jobs, the ones that stopped working first. */
export function ScheduledPanel({ cronJobs, state }: { cronJobs: CronJob[]; state: SourceState | undefined }) {
  return (
    <Section
      title="Scheduled jobs"
      testId="environment-scheduled"
      description="The platform's background jobs: backups, clean-up, cost and budget updates."
    >
      {cronJobs.length === 0 ? (
        <EmptyRow state={state}>No scheduled jobs found.</EmptyRow>
      ) : (
        <ul className="af-card m-0 list-none divide-y p-0">
          {cronJobs.map((cron) => (
            <li
              key={cron.name}
              className="px-4 py-2.5 text-[13px]"
              data-testid={`cron-job-${cron.name}`}
              data-state={cron.state}
            >
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <span className="flex min-w-0 max-w-full items-center gap-2">
                  <StatusDot tone={STATE_TONE[cron.state]} label={cron.state} />
                  <span className="min-w-0 truncate font-medium" style={{ color: "var(--ink)" }}>
                    {cron.name}
                  </span>
                </span>
                {cron.schedule && (
                  <span className="hidden font-mono text-[12px] sm:inline" style={{ color: "var(--ink-4)" }}>
                    {cron.schedule}
                  </span>
                )}
                {cron.running && (
                  <span className="ml-auto text-[12px]" style={{ color: "var(--ink-3)" }}>
                    Running now
                  </span>
                )}
              </div>
              <p className="m-0 mt-1" style={{ color: "var(--ink-3)" }}>
                {STATE_TEXT[cron.state]} · {lastWorked(cron)}
                {cron.lastFailedAt && cron.state !== "failing" ? ` · last failed ${formatAge(cron.lastFailedAt)}` : ""}
              </p>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}
