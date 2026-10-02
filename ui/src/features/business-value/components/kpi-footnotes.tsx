"use client";

import { formatSpend } from "@/features/costs/format";

import { formatCount, formatHours, missingFigure } from "../format";
import type { OrganizationValue } from "../schemas";
import { outcomeTypeLabel } from "../utils";
import { type KpiSource, RetryButton } from "./kpi-tiles";

const VALUE_NOTE =
  "Value counts only successful aai-cli and gog write actions. The handled rate and response time cover Web Chat and Email only.";

function plural(count: number, singular: string, pluralForm: string): string {
  return `${formatCount(count)} ${count === 1 ? singular : pluralForm}`;
}

export function KpiFootnotes({ value }: { value: KpiSource<OrganizationValue> }) {
  return (
    <div className="af-card mb-6 p-4" data-testid="kpi-footnotes">
      <h2 className="m-0 mb-2 text-[14px] font-semibold" style={{ color: "var(--ink)" }}>
        Top outcomes
      </h2>

      {value.error ? (
        <p className="m-0 mb-2 text-[13px] flex items-center gap-2" style={{ color: "var(--err)" }}>
          Unable to load
          <RetryButton onRetry={value.onRetry} />
        </p>
      ) : value.data ? (
        <>
          {value.data.topOutcomeTypes.length === 0 ? (
            <p className="m-0 mb-2 text-[13px]" style={{ color: "var(--ink-4)" }}>
              No successful writes in this period.
            </p>
          ) : (
            <ul className="m-0 mb-2 p-0 list-none flex flex-col gap-1 text-[13px]">
              {value.data.topOutcomeTypes.map((outcome) => (
                <li
                  key={outcome.outcomeType}
                  className="flex flex-wrap gap-x-3"
                  style={{ color: "var(--ink-3)" }}
                >
                  <span style={{ color: "var(--ink-2)" }}>
                    {outcomeTypeLabel(outcome.outcomeType)}
                  </span>
                  <span>{plural(outcome.successfulWrites, "write", "writes")}</span>
                  <span>{formatHours(outcome.minutesSaved)}</span>
                  <span>
                    {outcome.value === null
                      ? missingFigure(value.data!.totals.hourlyRateUsd !== null)
                      : formatSpend(outcome.value)}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <p className="m-0 mb-2 text-[12px]" style={{ color: "var(--ink-4)" }}>
            {plural(value.data.totals.unverifiedWrites, "unverified write", "unverified writes")}
            {" · "}
            {plural(
              value.data.totals.unclassifiedActions,
              "unclassified action",
              "unclassified actions",
            )}
          </p>
        </>
      ) : null}

      <p className="m-0 text-[12px]" style={{ color: "var(--ink-4)" }}>
        {VALUE_NOTE}
      </p>
    </div>
  );
}
