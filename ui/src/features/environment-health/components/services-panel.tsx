import type { CoreService, FiringAlert, SourceState } from "../schemas";
import { healthTone, type Tone } from "../utils";
import { AgentLabel, EmptyRow, Section, StatusDot } from "./section";

const SEVERITY_TONE: Record<string, Tone> = { critical: "err", warning: "warn", info: "muted" };

/** The platform's own services, by ready replicas, and the monitoring rules that are firing. */
export function ServicesPanel({
  services,
  alerts,
  workloadsState,
  monitoringState,
}: {
  services: CoreService[];
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
