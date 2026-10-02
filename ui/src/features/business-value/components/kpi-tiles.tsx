"use client";

import type { ReactNode } from "react";
import Link from "next/link";

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

const LOADING_FIGURE = "…";
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
        figure={({ totals }) => ({
          value: formatHours(totals.minutesSaved),
          hint: `${totals.successfulWrites.toLocaleString("en-US")} successful ${
            totals.successfulWrites === 1 ? "write" : "writes"
          }`,
        })}
      />
      <SourceTile
        source={value}
        label="Value"
        testId="kpi-value"
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
        figure={({ totals }) => ({ value: totals.requests.toLocaleString("en-US") })}
      />
      <SourceTile
        source={activity}
        label="Handled without failure"
        testId="kpi-handled"
        figure={({ totals }) => ({
          ...(totals.handledWithoutFailureRate === null
            ? { missing: NOT_ENOUGH_DATA }
            : { value: formatRate(totals.handledWithoutFailureRate) }),
          hint: `based on ${totals.handledCoverage.toLocaleString(
            "en-US",
          )} of ${totals.requests.toLocaleString("en-US")} requests · Web Chat and Email only`,
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
}: {
  source: KpiSource<T>;
  label: string;
  testId: string;
  figure: (data: T) => Figure;
}) {
  if (source.error) {
    return (
      <StatCard label={label} value={FAILED_FIGURE} testId={testId}>
        <RetryButton onRetry={source.onRetry} />
      </StatCard>
    );
  }
  if (!source.data) {
    return <StatCard label={label} value={LOADING_FIGURE} testId={testId} />;
  }
  const shown = figure(source.data);
  const hint = [shown.missing, shown.hint].filter(Boolean).join(" · ");
  return (
    <StatCard
      label={label}
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
