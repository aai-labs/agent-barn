import { formatBytes } from "@/features/resource-usage/format";

import type { IdleAgent } from "../schemas";
import { formatAge } from "../utils";
import { AgentLabel, EmptyRow, Section } from "./section";

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

/** What deleting the agent would free, as far as it is known. */
function holdings(row: IdleAgent): string {
  const parts: string[] = [];
  if (row.holdsPod) parts.push("Running pod");
  if (row.volumeClaims !== null && row.volumeClaims > 0) {
    parts.push(`${plural(row.volumeClaims, "volume", "volumes")} · ${formatBytes(row.requestedBytes ?? 0)}`);
  }
  if (row.restorePoints > 0) {
    parts.push(`${plural(row.restorePoints, "restore point", "restore points")} · ${formatBytes(row.restorePointBytes)}`);
  }
  if (parts.length > 0) return parts.join(" · ");
  // Pods and volumes could not be read, so "nothing" would be a guess.
  if (row.holdsPod === null || row.volumeClaims === null) return "What it holds can't be read right now";
  return "Holds no pod, volume or restore point";
}

/**
 * Agents no person has written to for a while, and what they hold. Only a person's message
 * counts as use: the platform wakes agents on its own, so a recent model call is shown for
 * context but does not keep an agent off the list.
 */
export function IdleAgentsPanel({ idle, idleAfterDays }: { idle: IdleAgent[]; idleAfterDays: number }) {
  return (
    <Section
      title="Idle agents"
      testId="environment-idle"
      description={`Running or stopped agents with no message from anyone in ${idleAfterDays} days. Candidates to stop or delete.`}
    >
      {idle.length === 0 ? (
        <EmptyRow>Every agent has been used recently.</EmptyRow>
      ) : (
        <ul className="af-card m-0 list-none divide-y p-0">
          {idle.map((row) => (
            <li key={row.agent.agentId} className="px-4 py-3 text-[13px]" data-testid="idle-agent">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <AgentLabel agent={row.agent} />
                <span className="ml-auto text-[12px]" style={{ color: "var(--ink-4)" }}>
                  {row.lastUserMessageAt
                    ? `Last message from a person ${formatAge(row.lastUserMessageAt)}`
                    : "Never written to"}
                </span>
              </div>
              <p className="m-0 mt-1" style={{ color: "var(--ink-3)" }}>
                {holdings(row)}
                {row.lastCallAt ? ` · last model call ${formatAge(row.lastCallAt)}` : ""}
              </p>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}
