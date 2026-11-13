import type { CronJob, ScheduledBackups, SourceState } from "../schemas";
import { formatAge, type Tone } from "../utils";
import { AgentLabel, EmptyRow, ExpandableList, Section, StatusDot } from "./section";

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

function every(minutes: number): string {
  if (minutes % 60 === 0) {
    const hours = minutes / 60;
    return `Every ${hours === 1 ? "hour" : `${hours} hours`}`;
  }
  return `Every ${minutes} minutes`;
}

/** How many agents are affected, so a failure across the platform reads as one, not as a long list. */
function backupsSummary(backups: ScheduledBackups): string {
  const { failedTotal, overdueTotal, runningAgents, failureWindowHours } = backups;
  const overdue = overdueTotal === 1 ? "1 more is overdue" : `${overdueTotal} more are overdue`;
  if (failedTotal === 0) {
    return `${overdueTotal} of ${runningAgents} running agents ${overdueTotal === 1 ? "is" : "are"} overdue for a backup`;
  }
  const failed = `${failedTotal} of ${runningAgents} running agents failed a backup in the last ${failureWindowHours} hours`;
  return overdueTotal === 0 ? failed : `${failed} · ${overdue}`;
}

/** Running agents whose scheduled backups fail or have stopped, the worst named. From the platform's own records. */
function BackupsList({ backups }: { backups: ScheduledBackups }) {
  if (!backups.enabled) {
    return <EmptyRow>Scheduled backups are switched off.</EmptyRow>;
  }
  const { failed, overdue, failureWindowHours } = backups;
  return (
    <>
      <p className="m-0 mb-2 text-[12.5px]" style={{ color: "var(--ink-4)" }}>
        {every(backups.intervalMinutes)} for each running agent.
      </p>
      {failed.length === 0 && overdue.length === 0 ? (
        <EmptyRow>Every running agent has a recent backup.</EmptyRow>
      ) : (
        <ExpandableList
          total={backups.failedTotal + backups.overdueTotal}
          summary={<span data-testid="backups-summary">{backupsSummary(backups)}</span>}
        >
          {failed.map((row) => (
            <li key={`failed-${row.agent.agentId}`} className="px-4 py-2.5 text-[13px]" data-testid="backup-failed">
              <span className="flex items-center gap-2">
                <StatusDot tone="err" label="failing" />
                <AgentLabel agent={row.agent} />
              </span>
              <p className="m-0 mt-1" style={{ color: "var(--ink-3)" }}>
                {row.failures} failed in the last {failureWindowHours} hours · latest {formatAge(row.lastFailedAt)}
              </p>
            </li>
          ))}
          {overdue.map((row) => (
            <li key={`overdue-${row.agent.agentId}`} className="px-4 py-2.5 text-[13px]" data-testid="backup-overdue">
              <span className="flex items-center gap-2">
                <StatusDot tone="warn" label="overdue" />
                <AgentLabel agent={row.agent} />
              </span>
              <p className="m-0 mt-1" style={{ color: "var(--ink-3)" }}>
                Overdue · {row.lastBackupAt ? `last backed up ${formatAge(row.lastBackupAt)}` : "never backed up"}
              </p>
            </li>
          ))}
        </ExpandableList>
      )}
    </>
  );
}

/** The platform's scheduled jobs, the ones that stopped working first, then the agents' scheduled backups. */
export function ScheduledPanel({
  cronJobs,
  backups,
  state,
}: {
  cronJobs: CronJob[];
  backups: ScheduledBackups;
  state: SourceState | undefined;
}) {
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

      <div data-testid="environment-backups">
        <h3 className="mb-2 mt-4 text-[13px] font-semibold" style={{ color: "var(--ink-2)" }}>
          Agent backups
        </h3>
        <BackupsList backups={backups} />
      </div>
    </Section>
  );
}
