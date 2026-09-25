"use client";

import { Skeleton } from "@/components/ui/skeleton";

import { formatSpend } from "../format";
import type { GroupMemoryCost } from "../schemas";

/**
 * Memory spend split across the org's memory groups.
 *
 * Memory has no per-agent attribution (agents share a pool), so the group is the
 * finest meaningful unit. The figures are apportioned from Honcho's authoritative
 * total by each pool's token share, so they sum to the "Memory cost" summary card.
 * The server already ranks them by cost.
 */
export function MemoryCostByGroup({
  groups,
  isLoading,
}: {
  groups: GroupMemoryCost[];
  isLoading: boolean;
}) {
  if (isLoading) {
    return (
      <div className="af-card mb-6 p-4" data-testid="memory-cost-by-group-skeleton">
        <Skeleton className="mb-4 h-4 w-40" />
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="mb-2 h-8 w-full" />
        ))}
      </div>
    );
  }

  if (groups.length === 0) return null;

  return (
    <div className="af-card mb-6 p-4" data-testid="memory-cost-by-group">
      <h2 className="m-0 mb-1 text-[14px] font-semibold" style={{ color: "var(--ink)" }}>
        Memory cost by group
      </h2>
      <p className="m-0 mb-3 text-[12px]" style={{ color: "var(--ink-4)" }}>
        Memory is shared within a group, so cost is tracked per group rather than per agent.
        Figures are apportioned from total memory spend by each group&rsquo;s share of use.
      </p>

      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-[13px]">
          <thead>
            <tr>
              <th
                scope="col"
                className="py-2 text-left font-medium"
                style={{ borderBottom: "1px solid var(--line)", color: "var(--ink-3)" }}
              >
                Group
              </th>
              <th
                scope="col"
                className="py-2 text-right font-medium"
                style={{ borderBottom: "1px solid var(--line)", color: "var(--ink-3)" }}
              >
                Memory cost
              </th>
            </tr>
          </thead>
          <tbody>
            {groups.map((group) => (
              <tr key={group.groupId}>
                <td className="py-2" style={{ color: "var(--ink-2)" }}>
                  {group.groupName}
                </td>
                <td className="py-2 text-right tabular-nums" style={{ color: "var(--ink)" }}>
                  {formatSpend(group.memoryCost)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
