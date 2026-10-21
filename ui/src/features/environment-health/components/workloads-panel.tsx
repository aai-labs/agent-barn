import type { EnvironmentHealth, PodIssue, SourceState } from "../schemas";
import { formatAgo } from "../utils";
import { AgentLabel, EmptyRow, Section, StatusDot } from "./section";

const KIND_LABEL: Record<PodIssue["kind"], string> = {
  infrastructure: "Platform",
  agent: "Agent",
  restore_point: "Restore point",
};

const STARTING = new Set(["ContainerCreating", "PodInitializing"]);

/** Why a pod needs a look, most telling first, then how often it restarted and why it last stopped. */
function issueText(issue: PodIssue): string {
  let state: string;
  if (issue.unschedulable) state = "No node has room for it";
  else if (issue.waitingReason && !STARTING.has(issue.waitingReason)) state = issue.waitingReason;
  else if (issue.phase === "Failed") state = "Failed";
  else if (issue.waitingReason) state = issue.waitingReason;
  else if (!issue.ready) state = "Not ready";
  else state = "Running";
  const restarts =
    issue.restartCount > 0 ? `restarted ${issue.restartCount} ${issue.restartCount === 1 ? "time" : "times"}` : null;
  const last = issue.terminationReason ? `last stopped: ${issue.terminationReason}` : null;
  return [state, restarts, last].filter(Boolean).join(" · ");
}

/** Pods that are failing, stuck or restarting, platform pods first. */
export function WorkloadsPanel({
  workloads,
  podsState,
}: {
  workloads: EnvironmentHealth["workloads"];
  podsState: SourceState | undefined;
}) {
  const { podsTotal, podsReady, issues } = workloads;
  return (
    <Section
      title="Workloads"
      testId="environment-workloads"
      description={
        podsState === "available"
          ? `${podsReady} of ${podsTotal} pods ready. Listed: pods that failed, can't be scheduled, are stuck, or keep restarting.`
          : undefined
      }
    >
      {issues.length === 0 ? (
        <EmptyRow state={podsState}>Every pod is running normally.</EmptyRow>
      ) : (
        <ul className="af-card m-0 list-none divide-y p-0">
          {issues.map((issue) => (
            <li key={issue.podName} className="px-4 py-3 text-[13px]" data-testid="pod-issue">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="flex min-w-0 max-w-full items-center gap-2">
                  <StatusDot tone={issue.ready ? "warn" : "err"} label={issue.ready ? "ready" : "not ready"} />
                  <span className="min-w-0 truncate font-mono text-[12.5px]" style={{ color: "var(--ink)" }}>
                    {issue.workloadName ?? issue.podName}
                  </span>
                </span>
                <span className="rounded px-1.5 py-0.5 text-[11px]" style={{ background: "var(--bg-soft)", color: "var(--ink-3)" }}>
                  {KIND_LABEL[issue.kind]}
                </span>
                <span className="ml-auto text-[12px]" style={{ color: "var(--ink-4)" }}>
                  {issue.lastRestartAt ? `Last restart ${formatAgo(issue.lastRestartAt)}` : `Started ${formatAgo(issue.createdAt)}`}
                </span>
              </div>
              <p className="m-0 mt-1" style={{ color: "var(--ink-2)" }}>
                {issueText(issue)}
              </p>
              {issue.agent && (
                <p className="m-0 mt-1 text-[12.5px]">
                  <AgentLabel agent={issue.agent} />
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}
