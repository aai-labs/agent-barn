"use client";


import { format } from "date-fns";

import { DateRangePicker } from "@/components/date-range-picker";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/shared/api/error/errors";
import { SpendOverTimeChart } from "@/features/costs/components/spend-over-time-chart";
import {
  formatModelLabel,
  formatSpend,
  formatTokens,
} from "@/features/costs/format";
import { useAgentCost } from "@/features/costs/hooks/use-agent-cost";
import { useCostUrlFilters } from "@/features/costs/hooks/use-cost-url-filters";
import type { Agent } from "../schemas";

const DATE_FILTER_DEFAULTS = { from: "", to: "" };

export function AboutTab({ agent }: { agent: Agent }) {
  const [dateFilters, setDateFilters] = useCostUrlFilters(DATE_FILTER_DEFAULTS);
  const { agentCost, isLoadingAgentCost, error } = useAgentCost(agent.id, {
    fromDate: dateFilters.from || undefined,
    toDate: dateFilters.to || undefined,
  });

  const resolvedWindowLabel = agentCost
    ? `${format(new Date(agentCost.fromDate), "MMM d, yyyy")} – ${format(
        new Date(agentCost.toDate),
        "MMM d, yyyy",
      )}`
    : "Loading…";

  return (
    <div className="flex flex-col gap-4">
      <div className="af-card p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2
              className="m-0 text-[14px] font-semibold"
              style={{ color: "var(--ink)" }}
            >
              Spend over time
            </h2>
            <p className="m-0 mt-1 text-[12px]" style={{ color: "var(--ink-4)" }}>
              What this agent has cost.
            </p>
          </div>

          <DateRangePicker
            from={dateFilters.from}
            to={dateFilters.to}
            onChange={(from, to) =>
              setDateFilters({ from: from || null, to: to || null })
            }
            placeholder={resolvedWindowLabel}
            width="16rem"
            ariaLabel="Date range"
          />
        </div>

        {error ? (
          <div
            className="flex h-[260px] items-center justify-center text-[13px]"
            style={{ color: "var(--ink-4)" }}
          >
            {/* A reader without cost access on this Agent is not looking at a
                failure, so it is not reported as one. */}
            {error instanceof ApiError && error.status === 403
              ? "You don't have access to this agent's costs."
              : "We couldn't load this agent's spend."}
          </div>
        ) : isLoadingAgentCost || !agentCost ? (
          <Skeleton className="h-[260px] w-full" />
        ) : (
          <SpendOverTimeChart
            series={agentCost.spendOverTime}
            granularity={agentCost.granularity}
          />
        )}
      </div>

      {agentCost && !error && (
        <div className="grid gap-3 sm:grid-cols-3">
          <CostStat label="Total spend" value={formatSpend(agentCost.totalCost)} />
          <CostStat
            label="Prompt tokens"
            value={formatTokens(agentCost.promptTokens)}
          />
          <CostStat
            label="Completion tokens"
            value={formatTokens(agentCost.completionTokens)}
          />
        </div>
      )}

      {agentCost && !error && agentCost.modelsBreakdown.length > 0 && (
        <div className="af-card p-4" data-testid="agent-cost-by-model">
          <h2
            className="m-0 mb-3 text-[14px] font-semibold"
            style={{ color: "var(--ink)" }}
          >
            Spend by model
          </h2>

          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-[13px]">
              <thead>
                <tr>
                  <th
                    scope="col"
                    className="py-2 text-left font-medium"
                    style={{ borderBottom: "1px solid var(--line)", color: "var(--ink-3)" }}
                  >
                    Model
                  </th>
                  <th
                    scope="col"
                    className="py-2 text-right font-medium"
                    style={{ borderBottom: "1px solid var(--line)", color: "var(--ink-3)" }}
                  >
                    Spend
                  </th>
                  <th
                    scope="col"
                    className="py-2 text-right font-medium"
                    style={{ borderBottom: "1px solid var(--line)", color: "var(--ink-3)" }}
                  >
                    Tokens
                  </th>
                </tr>
              </thead>
              <tbody>
                {agentCost.modelsBreakdown.map((entry) => (
                  <tr key={entry.model}>
                    <td
                      className="max-w-[1px] truncate py-2"
                      style={{ color: "var(--ink-2)" }}
                      title={entry.model}
                    >
                      {formatModelLabel(entry.model)}
                    </td>
                    <td
                      className="py-2 text-right tabular-nums"
                      style={{ color: "var(--ink)" }}
                    >
                      {formatSpend(entry.totalCost)}
                    </td>
                    <td
                      className="py-2 text-right tabular-nums"
                      style={{ color: "var(--ink-3)" }}
                    >
                      {formatTokens(entry.promptTokens + entry.completionTokens)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function CostStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="af-card p-4">
      <div className="text-[12px]" style={{ color: "var(--ink-4)" }}>
        {label}
      </div>
      <div
        className="mt-1 text-[20px] font-semibold tabular-nums"
        style={{ color: "var(--ink)" }}
      >
        {value}
      </div>
    </div>
  );
}
