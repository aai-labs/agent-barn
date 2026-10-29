import type { SourceState, WarningEvent } from "../schemas";
import { formatAgo } from "../utils";
import { AgentLabel, EmptyRow, Section } from "./section";

/**
 * The namespace's recent Warning Events. The cluster's own message is never shown: each Event
 * carries a fixed explanation, and a quota rejection the figures rebuilt from it.
 */
export function EventsPanel({ events, state }: { events: WarningEvent[]; state: SourceState | undefined }) {
  return (
    <Section
      title="Recent warnings"
      testId="environment-events"
      description="Warnings Kubernetes reported in the last six hours, newest first."
    >
      {events.length === 0 ? (
        <EmptyRow state={state}>No warnings in the last six hours.</EmptyRow>
      ) : (
        <ul className="af-card m-0 list-none divide-y p-0">
          {events.map((event, index) => (
            <li key={`${event.reason}-${event.objectName ?? ""}-${index}`} className="px-4 py-3 text-[13px]" data-testid="warning-event">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="font-medium" style={{ color: "var(--ink)" }}>
                  {event.reason}
                </span>
                {event.objectName && (
                  <span className="min-w-0 truncate font-mono text-[12px]" style={{ color: "var(--ink-3)" }}>
                    {event.objectKind}/{event.objectName}
                  </span>
                )}
                <span className="ml-auto text-[12px]" style={{ color: "var(--ink-4)" }}>
                  {event.count > 1 ? `${event.count}× · ` : ""}
                  {formatAgo(event.lastSeen)}
                </span>
              </div>
              <p className="m-0 mt-1 leading-relaxed" style={{ color: "var(--ink-3)" }}>
                {event.explanation}
              </p>
              {event.detail && (
                <p className="m-0 mt-1 font-mono text-[12px]" style={{ color: "var(--ink-2)" }}>
                  {event.detail}
                </p>
              )}
              {event.agent && (
                <p className="m-0 mt-1 text-[12.5px]">
                  <AgentLabel agent={event.agent} />
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}
