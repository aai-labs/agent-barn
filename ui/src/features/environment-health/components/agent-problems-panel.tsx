import type { FailedAgent, SourceState, UnhealthyRuntime } from "../schemas";
import { formatAgo } from "../utils";
import { AgentLabel, EmptyRow, Section, StatusDot } from "./section";

function runtimeText(row: UnhealthyRuntime): string {
  const connection =
    row.everConnected === false
      ? "Its runtime has never connected since the pod started."
      : row.everConnected === true
        ? "Its runtime lost a connection it had."
        : "Its runtime reports it is not working.";
  if (row.podReady === true) return `${connection} The pod itself looks ready.`;
  if (row.podReady === false) return `${connection} The pod is not ready either.`;
  return connection;
}

/** Agents that failed to start, and agents whose runtime is not working even if the pod is up. */
export function AgentProblemsPanel({
  failed,
  unhealthy,
  monitoringState,
}: {
  failed: FailedAgent[];
  unhealthy: UnhealthyRuntime[];
  monitoringState: SourceState | undefined;
}) {
  return (
    <Section
      title="Agents needing attention"
      testId="environment-agents"
      description="Agents that failed to start, with the reason, and agents whose runtime is down while their pod may look fine."
    >
      {failed.length === 0 && unhealthy.length === 0 ? (
        <EmptyRow>No agents need attention.</EmptyRow>
      ) : (
        <ul className="af-card m-0 list-none divide-y p-0">
          {failed.map((row) => (
            <li key={`failed-${row.agent.agentId}`} className="px-4 py-3 text-[13px]" data-testid="failed-agent">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <StatusDot tone="err" label="failed" />
                <AgentLabel agent={row.agent} />
                <span className="ml-auto text-[12px]" style={{ color: "var(--ink-4)" }}>
                  Failed {formatAgo(row.updatedAt)}
                </span>
              </div>
              {row.summary && (
                <p className="m-0 mt-1 leading-relaxed" style={{ color: "var(--ink-3)" }}>
                  {row.summary}
                </p>
              )}
              {row.detail && (
                <p className="m-0 mt-1 font-mono text-[12px]" style={{ color: "var(--ink-2)" }}>
                  {row.detail}
                </p>
              )}
            </li>
          ))}
          {unhealthy.map((row) => (
            <li key={`runtime-${row.agent.agentId}`} className="px-4 py-3 text-[13px]" data-testid="unhealthy-runtime">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <StatusDot tone="warn" label="runtime unhealthy" />
                <AgentLabel agent={row.agent} />
              </div>
              <p className="m-0 mt-1 leading-relaxed" style={{ color: "var(--ink-3)" }}>
                {runtimeText(row)}
              </p>
            </li>
          ))}
        </ul>
      )}
      {monitoringState && monitoringState !== "available" && (
        <p className="m-0 mt-2 text-[12px]" style={{ color: "var(--ink-4)" }}>
          Runtime health comes from monitoring, which is not available, so only failed starts are listed.
        </p>
      )}
    </Section>
  );
}
