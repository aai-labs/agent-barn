import { formatBytes } from "@/features/resource-usage/format";

import type { SourceState, VolumeAllocation, VolumeGroup } from "../schemas";
import { VOLUME_GROUP_LABELS } from "../utils";
import { AgentLabel, EmptyRow, Section } from "./section";

const GROUP_COLOR: Record<VolumeGroup, string> = {
  infrastructure: "var(--ink-3)",
  active_agents: "var(--ok)",
  stopped_agents: "var(--ink-4)",
  restore_points: "var(--ink-2)",
  orphaned: "var(--err)",
};

/**
 * Every volume claim in the namespace, by what it belongs to. A stopped agent keeps its
 * volume, and an orphaned one is left behind by an agent that no longer exists; both count
 * against the storage quota.
 */
export function VolumesPanel({ volumes, state }: { volumes: VolumeAllocation; state: SourceState | undefined }) {
  const total = volumes.totalRequestedBytes;
  const groups = volumes.groups.filter((group) => group.claims > 0);
  return (
    <Section
      title="Storage"
      testId="environment-volumes"
      description={
        state === "available"
          ? `${volumes.totalClaims} volume claims requesting ${formatBytes(total)} in all.`
          : undefined
      }
    >
      {groups.length === 0 ? (
        <EmptyRow state={state}>No volume claims in the namespace.</EmptyRow>
      ) : (
        <div className="af-card px-4 py-3.5">
          {total > 0 && (
            <div
              className="mb-3 flex h-2 w-full overflow-hidden rounded-full"
              style={{ background: "var(--bg-soft)" }}
              role="img"
              aria-label="Storage requested by group"
            >
              {groups.map((group) => (
                <div
                  key={group.group}
                  style={{ width: `${(group.requestedBytes / total) * 100}%`, background: GROUP_COLOR[group.group] }}
                />
              ))}
            </div>
          )}
          <dl className="m-0 grid gap-x-6 gap-y-2" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(min(160px, 100%), 1fr))" }}>
            {groups.map((group) => (
              <div key={group.group} className="min-w-0" data-testid={`volume-group-${group.group}`}>
                <dt className="flex items-center gap-1.5 text-[12px]" style={{ color: "var(--ink-4)" }}>
                  <span className="inline-block h-2 w-2 rounded-sm" style={{ background: GROUP_COLOR[group.group] }} aria-hidden />
                  {VOLUME_GROUP_LABELS[group.group]}
                </dt>
                <dd className="m-0 text-[14px] font-semibold" style={{ color: "var(--ink)" }}>
                  {formatBytes(group.requestedBytes)}{" "}
                  <span className="text-[12px] font-normal" style={{ color: "var(--ink-4)" }}>
                    · {group.claims} {group.claims === 1 ? "claim" : "claims"}
                  </span>
                </dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      {volumes.attention.length > 0 && (
        <ul className="af-card m-0 mt-3 list-none divide-y p-0" data-testid="volume-attention">
          {volumes.attention.map((claim) => (
            <li key={claim.name} className="px-4 py-2.5 text-[13px]">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="min-w-0 truncate font-mono text-[12.5px]" style={{ color: "var(--ink)" }}>
                  {claim.name}
                </span>
                <span className="text-[12px]" style={{ color: "var(--ink-4)" }}>
                  {claim.requestedBytes !== null && formatBytes(claim.requestedBytes)}
                </span>
                <span className="ml-auto text-[12px]" style={{ color: claim.group === "orphaned" ? "var(--err)" : "var(--warn)" }}>
                  {claim.group === "orphaned" ? "Orphaned" : (claim.phase ?? "Unknown state")}
                </span>
              </div>
              {/* An orphan's name already carries its id; only a live agent adds anything. */}
              {claim.agent?.agentName && (
                <p className="m-0 mt-1 text-[12.5px]">
                  <AgentLabel agent={claim.agent} />
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}
