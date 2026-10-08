"use client";

import type { ReactNode } from "react";
import Link from "next/link";

import { Skeleton } from "@/components/ui/skeleton";
import { StatCard } from "@/features/costs/components/cost-summary-cards";
import { formatSpend } from "@/features/costs/format";

import {
  NOT_ENOUGH_DATA,
  formatHours,
  formatRate,
  formatValuePerDollar,
  missingFigure,
} from "../format";
import type { OrganizationActivity, OrganizationValue } from "../schemas";
import { CalculationHint } from "./calculation-hint";

const FAILED_FIGURE = "Unable to load";
const MISSING_FIGURE = "—";

export type KpiSource<T> = {
  data: T | null;
  error: unknown;
  onRetry: () => void;
};

type Figure = {
  value?: string;
  missing?: string;
  hint?: string;
  extra?: ReactNode;
};

export function KpiTiles({
  value,
  activity,
  spendHref,
}: {
  value: KpiSource<OrganizationValue>;
  activity: KpiSource<OrganizationActivity>;
  spendHref: string;
}) {
  return (
    <div className="grid grid-cols-1 gap-3 mb-6 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-6">
      <SourceTile
        source={value}
        label="Hours saved"
        testId="kpi-hours-saved"
        calculation={
          <>
            <p className="m-0">Successful actions × minutes saved per outcome ÷ 60.</p>
            <p className="m-0">An estimate of human work saved. Only successful, classified aai-cli and gog write actions count. Adjust the minutes per outcome in Value settings.</p>
          </>
        }
        figure={({ totals }) => ({
          value: formatHours(totals.minutesSaved),
          hint: `Estimated from ${totals.successfulWrites.toLocaleString("en-US")} successful ${
            totals.successfulWrites === 1 ? "write" : "writes"
          }`,
        })}
      />
      <SourceTile
        source={value}
        label="Value"
        testId="kpi-value"
        calculation={
          <>
            <p className="m-0">Hours saved × hourly rate.</p>
            <p className="m-0">Estimated human-work value in USD. Set the hourly rate in Value settings. Changing it recalculates past periods too.</p>
          </>
        }
        figure={({ totals }) =>
          totals.value === null || totals.hourlyRateUsd === null
            ? { missing: missingFigure(totals.hourlyRateUsd !== null) }
            : {
                value: formatSpend(totals.value),
                hint: `at ${formatSpend(totals.hourlyRateUsd)}/h`,
              }
        }
      />
      <SourceTile
        source={value}
        label="LLM spend"
        testId="kpi-spend"
        calculation={<p className="m-0">The sum of recorded LLM costs for this organization in the selected period. It includes all model usage, including work that produced no valued action.</p>}
        figure={({ totals }) => ({
          value: formatSpend(totals.spend),
          extra: (
            <Link
              href={spendHref}
              className="text-[12px] underline"
              style={{ color: "var(--ink-3)" }}
            >
              View in Costs
            </Link>
          ),
        })}
      />
      <SourceTile
        source={value}
        label="Value per dollar spent"
        testId="kpi-value-per-dollar"
        calculation={
          <>
            <p className="m-0">Estimated value ÷ LLM spend.</p>
            <p className="m-0">For example, $90 of value ÷ $10 of spend gives $9 per $1 spent. Requires an hourly rate and spend greater than zero.</p>
          </>
        }
        figure={({ totals }) =>
          totals.valueToSpendRatio === null
            ? { missing: missingFigure(totals.hourlyRateUsd !== null) }
            : { value: formatValuePerDollar(totals.valueToSpendRatio) }
        }
      />
      <SourceTile
        source={activity}
        label="Requests"
        testId="kpi-requests"
        calculation={<p className="m-0">Inbound messages + accepted webhook invocations in the selected period. Requests from natively connected channels count too.</p>}
        figure={({ totals }) => ({ value: totals.requests.toLocaleString("en-US") })}
      />
      <SourceTile
        source={activity}
        label="Handled without failure"
        testId="kpi-handled"
        calculation={<p className="m-0">Successful deliveries ÷ (successful + failed deliveries) × 100. Covers only requests routed through Agent Barn that have a final delivery outcome. The count below shows that coverage.</p>}
        figure={({ totals }) => ({
          ...(totals.handledWithoutFailureRate === null
            ? { missing: NOT_ENOUGH_DATA }
            : { value: formatRate(totals.handledWithoutFailureRate) }),
          hint: `based on ${totals.handledCoverage.toLocaleString(
            "en-US",
          )} of ${totals.requests.toLocaleString("en-US")} requests routed through Agent Barn`,
        })}
      />
    </div>
  );
}

function SourceTile<T>({
  source,
  label,
  testId,
  figure,
  calculation,
}: {
  source: KpiSource<T>;
  label: string;
  testId: string;
  figure: (data: T) => Figure;
  calculation: ReactNode;
}) {
  const tileLabel = (
    <span className="inline-flex items-center gap-1">
      {label}
      <CalculationHint label={label}>{calculation}</CalculationHint>
    </span>
  );
  if (source.error) {
    return (
      <StatCard label={tileLabel} value={FAILED_FIGURE} testId={testId}>
        <RetryButton onRetry={source.onRetry} />
      </StatCard>
    );
  }
  if (!source.data) {
    return (
      <div className="af-card px-4 py-3.5" data-testid="kpi-tile-skeleton">
        <Skeleton className="h-3 w-16 mb-2" />
        <Skeleton className="h-6 w-20" />
      </div>
    );
  }
  const shown = figure(source.data);
  const hint = [shown.missing, shown.hint].filter(Boolean).join(" · ");
  return (
    <StatCard
      label={tileLabel}
      value={shown.missing ? MISSING_FIGURE : (shown.value ?? MISSING_FIGURE)}
      hint={hint || undefined}
      testId={testId}
    >
      {shown.extra}
    </StatCard>
  );
}

export function RetryButton({ onRetry }: { onRetry: () => void }) {
  return (
    <button
      type="button"
      className="text-[12px] underline"
      style={{ color: "var(--ink-3)" }}
      onClick={onRetry}
    >
      Retry
    </button>
  );
}
