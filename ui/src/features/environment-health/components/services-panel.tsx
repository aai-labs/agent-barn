import type { CoreService, DeployedVersion, FiringAlert, SourceState } from "../schemas";
import { formatAge, healthTone, shortSha, TONE_COLOR, type Tone } from "../utils";
import { AgentLabel, EmptyRow, Section, StatusDot } from "./section";

const SEVERITY_TONE: Record<string, Tone> = { critical: "err", warning: "warn", info: "muted" };

const ROLLOUT_TEXT: Record<NonNullable<CoreService["rollout"]>, string | null> = {
  complete: null,
  in_progress: "Rolling out",
  stuck: "Rollout stuck",
};

/** Which build is running and how long ago it went out, so a deploy that stopped landing is visible. */
function DeployedLine({ deployed }: { deployed: DeployedVersion | null }) {
  if (!deployed) return null;
  const others = deployed.behind.join(", ");
  return (
    <div className="mb-3 text-[13px] leading-relaxed" data-testid="environment-deployed">
      <p className="m-0" style={{ color: "var(--ink-2)" }}>
        Build <span className="font-mono">{shortSha(deployed.buildSha)}</span>
        {deployed.rolledOutAt && (
          <span title={new Date(deployed.rolledOutAt).toLocaleString()}>
            , rolled out {formatAge(deployed.rolledOutAt)}
          </span>
        )}
        .
      </p>
      {deployed.mixed && (
        <p className="m-0 mt-1" style={{ color: TONE_COLOR.warn }}>
          {others} {deployed.behind.length === 1 ? "is" : "are"} on another build.
        </p>
      )}
    </div>
  );
}

/** The platform's own services, by ready replicas, and the monitoring rules that are firing. */
export function ServicesPanel({
  services,
  deployed,
  alerts,
  workloadsState,
  monitoringState,
}: {
  services: CoreService[];
  deployed: DeployedVersion | null;
  alerts: FiringAlert[];
  workloadsState: SourceState | undefined;
  monitoringState: SourceState | undefined;
}) {
  return (
    <Section
      title="Platform services"
      testId="environment-services"
      description="The API, UI, workers, databases and the other services agents depend on."
    >
      <DeployedLine deployed={deployed} />
      {services.length === 0 ? (
        <EmptyRow state={workloadsState}>No platform services found.</EmptyRow>
      ) : (
        <ul className="af-card m-0 list-none divide-y p-0" style={{ borderColor: "var(--line)" }}>
          {services.map((service) => (
            <li
              key={`${service.kind}/${service.name}`}
              className="flex items-center gap-3 px-4 py-2.5 text-[13px]"
              data-testid={`service-${service.name}`}
              data-level={service.level}
            >
              <StatusDot tone={healthTone(service.level)} label={service.level} />
              <span className="min-w-0 flex-1 truncate font-medium" style={{ color: "var(--ink)" }}>
                {service.name}
              </span>
              {service.rollout && ROLLOUT_TEXT[service.rollout] && (
                <span className="text-[12px]" style={{ color: TONE_COLOR[service.rollout === "stuck" ? "warn" : "muted"] }}>
                  {ROLLOUT_TEXT[service.rollout]}
                </span>
              )}
              {service.buildSha && (
                <span className="hidden font-mono text-[12px] sm:inline" style={{ color: "var(--ink-4)" }}>
                  {shortSha(service.buildSha)}
                </span>
              )}
              <span className="hidden text-[12px] sm:inline" style={{ color: "var(--ink-4)" }}>
                {service.kind}
              </span>
              <span className="tabular-nums" style={{ color: "var(--ink-3)" }}>
                {service.readyReplicas}/{service.desiredReplicas} ready
              </span>
            </li>
          ))}
        </ul>
      )}

      <h3 className="mb-2 mt-4 text-[13px] font-semibold" style={{ color: "var(--ink-2)" }}>
        Firing alerts
      </h3>
      {alerts.length === 0 ? (
        <EmptyRow state={monitoringState}>No alerts are firing.</EmptyRow>
      ) : (
        <ul className="af-card m-0 list-none divide-y p-0" data-testid="environment-alerts">
          {alerts.map((alert) => (
            <li
              key={`${alert.name}/${alert.agent?.agentId ?? ""}`}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-[13px]"
            >
              <StatusDot tone={SEVERITY_TONE[alert.severity ?? ""] ?? "muted"} label={alert.severity ?? undefined} />
              <span className="font-medium" style={{ color: "var(--ink)" }}>
                {alert.name}
              </span>
              {alert.agent && <AgentLabel agent={alert.agent} />}
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}
