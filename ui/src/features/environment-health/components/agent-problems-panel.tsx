import type { FailedAgent, SourceState, UnhealthyRuntime } from "../schemas";
import { formatAgo } from "../utils";
import { AgentLabel, EmptyRow, Section, StatusDot, ExpandableList } from "./section";

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
/** How many of each, so a failure across the platform reads as one before the rows. */
function agentsSummary(failedTotal: number, unhealthyTotal: number): string {
  const agents = (count: number) => `${count} ${count === 1 ? "agent" : "agents"}`;
  const parts = [
    failedTotal > 0 ? `${agents(failedTotal)} failed to start` : null,
    unhealthyTotal > 0 ? `${agents(unhealthyTotal)} with the runtime down` : null,
  ];
  return parts.filter(Boolean).join(" · ");
}

export function AgentProblemsPanel({
  failed,
  unhealthy,
  failedTotal,
  unhealthyTotal,
  monitoringState,
}: {
  failed: FailedAgent[];
  unhealthy: UnhealthyRuntime[];
  failedTotal: number;
  unhealthyTotal: number;
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
        <ExpandableList total={failedTotal + unhealthyTotal} summary={agentsSummary(failedTotal, unhealthyTotal)}>
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
        </ExpandableList>
      )}
      {monitoringState && monitoringState !== "available" && (
        <p className="m-0 mt-2 text-[12px]" style={{ color: "var(--ink-4)" }}>
          Runtime health comes from monitoring, which is not available, so only failed starts are listed.
        </p>
      )}
    </Section>
  );
}
