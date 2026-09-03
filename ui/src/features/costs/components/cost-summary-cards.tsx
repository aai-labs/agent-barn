"use client";

import type { ReactNode } from "react";

import { Skeleton } from "@/components/ui/skeleton";

import { formatCallSpend, formatSpend, formatTokens } from "../format";
import type { CostSummary } from "../schemas";

interface CostSummaryCardsProps {
  summary: CostSummary | null;
  isLoading: boolean;
  /** Extra cards the platform surface adds after the shared ones. */
  children?: ReactNode;
  cardCount?: number;
}

export function CostSummaryCards({
  summary,
  isLoading,
  children,
  cardCount = 5,
}: CostSummaryCardsProps) {
  if (isLoading || !summary) {
    return (
      <div
        data-testid="cost-summary-skeleton"
        className="grid gap-3 mb-6"
        style={{ gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}
      >
        {Array.from({ length: cardCount }).map((_, i) => (
          <div key={i} className="af-card px-4 py-3.5">
            <Skeleton className="h-3 w-16 mb-2" />
            <Skeleton className="h-6 w-20" />
          </div>
        ))}
      </div>
    );
  }

  return (
    <div
      className="grid gap-3 mb-6"
      style={{ gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}
    >
      <StatCard
        label="Total spend"
        value={formatSpend(summary.totalSpend)}
        hint={`${summary.totalCalls.toLocaleString()} ${summary.totalCalls === 1 ? "call" : "calls"}`}
        testId="cost-total-spend"
      />
      <StatCard
        label="Active agents"
        value={summary.activeAgents.toLocaleString()}
        hint="with spend in this period"
        testId="cost-active-agents"
      />
      <StatCard
        label="Top model"
        value={summary.topModel ? shortModel(summary.topModel) : "—"}
        hint={summary.topModel ? formatSpend(summary.topModelSpend) : "no spend yet"}
        testId="cost-top-model"
      />
      <StatCard
        label="Cost per call"
        value={formatCallSpend(summary.avgCostPerCall)}
        hint="average"
        testId="cost-per-call"
      />
      <StatCard
        label="Prompt tokens"
        value={formatTokens(summary.avgPromptTokens)}
        hint="average per call"
        testId="cost-avg-prompt-tokens"
      />
      {children}
    </div>
  );
}

/** Provider-qualified ids are too long for a card. The last segment is the name
 *  people actually say. */
export function shortModel(model: string): string {
  return model.split("/").at(-1) ?? model;
}

export function StatCard({
  label,
  value,
  hint,
  testId,
}: {
  label: string;
  value: string;
  hint?: string;
  testId?: string;
}) {
  return (
    <div className="af-card px-4 py-3.5" data-testid={testId}>
      <p className="text-[12px] m-0 mb-1" style={{ color: "var(--ink-4)" }}>
        {label}
      </p>
      <p
        className="text-[20px] font-semibold m-0 truncate"
        style={{ color: "var(--ink)" }}
        title={value}
      >
        {value}
      </p>
      {hint && (
        <p className="text-[12px] m-0 mt-0.5" style={{ color: "var(--ink-4)" }}>
          {hint}
        </p>
      )}
    </div>
  );
}
