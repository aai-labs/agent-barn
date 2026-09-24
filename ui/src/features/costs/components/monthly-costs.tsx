"use client";

import { memo } from "react";
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";

import { AppErrorState } from "@/components/app-error-state";
import {
  type ChartConfig,
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart";
import { Skeleton } from "@/components/ui/skeleton";

import {
  formatCallSpend,
  formatChange,
  formatMonth,
  formatMonthShort,
  formatSpend,
  formatSpendCompact,
  formatTokens,
  spendChange,
} from "../format";
import type { MonthlyCost } from "../schemas";

interface MonthlyCostsProps {
  months: MonthlyCost[] | null;
  isLoading: boolean;
  error: unknown;
  onRetry: () => void;
  /** Adds the active-agents column; pointless on a single Agent's page. */
  showAgents?: boolean;
}

const CHART_CONFIG = {
  spend: { label: "Spend", color: "var(--ink-3)" },
  projectedRest: { label: "Projected rest of month", color: "var(--ink-4)" },
} satisfies ChartConfig;

/**
 * The months from the first one with any calls onward.
 *
 * The server fills every month in the window, which is right for a quiet month
 * between two busy ones but wrong for the months before anything happened: those
 * are "no history yet", not "spent nothing". Counting them would divide a new
 * Agent's spend by a year it did not exist for and pad the table with empty rows.
 * Calls rather than spend mark the start, so a month of failed or not-yet-healed
 * calls still counts as activity. With no calls at all, only the month in progress
 * is kept, so the section still says where this month stands.
 */
export function monthsWithHistory(months: MonthlyCost[]): MonthlyCost[] {
  const first = months.findIndex((month) => month.calls > 0);
  if (first === -1) return months.filter((month) => month.isCurrent);
  return months.slice(first);
}

/**
 * Spend per calendar month, with the month in progress projected to its end.
 *
 * Independent of the page's date range by design: the point is to compare whole
 * months, and a range picked for the charts would cut through the first and last.
 * Every other filter on the page still applies.
 *
 * Memoised for the same reason as the charts panel: recharts redraws from scratch
 * on every render, and the pages above re-render on router context changes.
 */
export const MonthlyCosts = memo(function MonthlyCosts({
  months,
  isLoading,
  error,
  onRetry,
  showAgents = true,
}: MonthlyCostsProps) {
  return (
    <section className="af-card p-4 mb-6" data-testid="monthly-costs">
      <h2
        className="text-[14px] font-semibold m-0 mb-1"
        style={{ color: "var(--ink)" }}
      >
        Monthly spend
      </h2>
      <p className="text-[12px] m-0 mb-4" style={{ color: "var(--ink-4)" }}>
        Whole calendar months (UTC) under these filters, from the first month
        with calls. The date range does not apply here.
      </p>

      {error ? (
        <AppErrorState
          title="Unable to load monthly spend"
          description="Something went wrong reading the monthly totals."
          onRetry={onRetry}
          className="min-h-[12rem] p-0"
        />
      ) : isLoading || !months ? (
        <div data-testid="monthly-costs-skeleton">
          <Skeleton className="h-[64px] w-full mb-4" />
          <Skeleton className="h-[200px] w-full mb-4" />
          <Skeleton className="h-[160px] w-full" />
        </div>
      ) : (
        <>
          <MonthlyHeadline months={months} />
          <MonthlySpendChart months={monthsWithHistory(months)} />
          <MonthlyTable months={monthsWithHistory(months)} showAgents={showAgents} />
        </>
      )}
    </section>
  );
});

function MonthlyHeadline({ months }: { months: MonthlyCost[] }) {
  const current = months.find((month) => month.isCurrent) ?? null;
  const currentIndex = current ? months.indexOf(current) : months.length;
  const previous = currentIndex > 0 ? months[currentIndex - 1] : null;
  // "Last month" reads the full list: a $0 August is still what August cost.
  // The average and total only count months since activity began.
  const history = monthsWithHistory(months);
  const closed = history.filter((month) => !month.isCurrent);
  const average =
    closed.length > 0
      ? closed.reduce((sum, month) => sum + month.spend, 0) / closed.length
      : null;

  return (
    <div
      className="grid gap-3 mb-4"
      style={{ gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))" }}
    >
      <Headline
        label="This month so far"
        value={current ? formatSpend(current.spend) : "—"}
        hint={
          current?.projectedSpend != null
            ? `on pace for ${formatSpend(current.projectedSpend)}`
            : undefined
        }
        testId="monthly-current"
      />
      <Headline
        label="Last month"
        value={previous ? formatSpend(previous.spend) : "—"}
        hint={previous ? formatMonth(previous.month) : undefined}
        testId="monthly-previous"
      />
      <Headline
        label="Monthly average"
        value={average !== null ? formatSpend(average) : "—"}
        hint={
          closed.length > 0
            ? `over ${closed.length} full ${closed.length === 1 ? "month" : "months"}`
            : "no full month yet"
        }
        testId="monthly-average"
      />
      <Headline
        label="Total"
        value={formatSpend(history.reduce((sum, month) => sum + month.spend, 0))}
        hint={`${history.length} ${history.length === 1 ? "month" : "months"}`}
        testId="monthly-total"
      />
    </div>
  );
}

function Headline({
  label,
  value,
  hint,
  testId,
}: {
  label: string;
  value: string;
  hint?: string;
  testId: string;
}) {
  return (
    <div data-testid={testId}>
      <p className="text-[12px] m-0 mb-0.5" style={{ color: "var(--ink-4)" }}>
        {label}
      </p>
      <p
        className="text-[18px] font-semibold m-0 tabular-nums"
        style={{ color: "var(--ink)" }}
      >
        {value}
      </p>
      {hint && (
        <p className="text-[12px] m-0" style={{ color: "var(--ink-4)" }}>
          {hint}
        </p>
      )}
    </div>
  );
}

function MonthlySpendChart({ months }: { months: MonthlyCost[] }) {
  // The month in progress stacks its projected remainder on top of what it has
  // spent so far, drawn as an outline so it cannot be mistaken for real spend.
  const data = months.map((month) => ({
    month: month.month,
    spend: month.spend,
    projectedRest:
      month.projectedSpend != null
        ? Math.max(month.projectedSpend - month.spend, 0)
        : undefined,
  }));
  const hasProjection = data.some((row) => row.projectedRest);

  return (
    <div className="mb-4">
      <ChartContainer config={CHART_CONFIG} className="h-[200px] w-full">
        <BarChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="month"
            tickFormatter={(value: string) => formatMonthShort(value)}
            tickLine={false}
            axisLine={false}
            interval={0}
            tick={{ fontSize: 11 }}
          />
          <YAxis
            tickLine={false}
            axisLine={false}
            width={64}
            tickFormatter={formatSpendCompact}
            tick={{ fontSize: 11 }}
          />
          <ChartTooltip
            content={
              <ChartTooltipContent
                labelFormatter={(value) => formatMonth(String(value))}
                formatter={(value, name) => (
                  <span className="flex w-full justify-between gap-3">
                    <span style={{ color: "var(--ink-3)" }}>
                      {CHART_CONFIG[name as keyof typeof CHART_CONFIG]?.label ??
                        String(name)}
                    </span>
                    <span className="font-medium tabular-nums">
                      {formatSpend(Number(value))}
                    </span>
                  </span>
                )}
              />
            }
          />
          <Bar
            dataKey="spend"
            stackId="month"
            fill="var(--color-spend)"
            isAnimationActive={false}
            maxBarSize={40}
          />
          <Bar
            dataKey="projectedRest"
            stackId="month"
            fill="transparent"
            stroke="var(--color-projectedRest)"
            strokeDasharray="4 3"
            isAnimationActive={false}
            maxBarSize={40}
          />
        </BarChart>
      </ChartContainer>
      {hasProjection && (
        <p className="text-[12px] m-0 mt-1" style={{ color: "var(--ink-4)" }}>
          Dashed outline: the rest of this month, projected at its pace so far.
        </p>
      )}
    </div>
  );
}

const TH = "py-2 px-2 font-medium first:pl-0 last:pr-0";
const TD = "py-2 px-2 tabular-nums first:pl-0 last:pr-0";

function MonthlyTable({
  months,
  showAgents,
}: {
  months: MonthlyCost[];
  showAgents: boolean;
}) {
  // Newest first: the month in progress and the one before it are what a reader
  // opens this table for. Change is computed in chronological order first.
  const rows = months
    .map((month, index) => {
      const previous = index > 0 ? months[index - 1] : null;
      // The month in progress is compared on its projection: month-to-date against
      // a whole month would read as a fall every month until the last day.
      const basis = month.isCurrent
        ? (month.projectedSpend ?? month.spend)
        : month.spend;
      return {
        month,
        change: previous ? spendChange(basis, previous.spend) : null,
      };
    })
    .reverse();

  const headerStyle = {
    borderBottom: "1px solid var(--line)",
    color: "var(--ink-3)",
  };

  return (
    <div className="overflow-x-auto">
      <table
        className="w-full border-collapse text-[13px]"
        data-testid="monthly-costs-table"
      >
        <thead>
          <tr>
            <th scope="col" className={`${TH} text-left`} style={headerStyle}>
              Month
            </th>
            <th scope="col" className={`${TH} text-right`} style={headerStyle}>
              Spend
            </th>
            <th scope="col" className={`${TH} text-right`} style={headerStyle}>
              vs. prior
            </th>
            <th scope="col" className={`${TH} text-right`} style={headerStyle}>
              Calls
            </th>
            <th scope="col" className={`${TH} text-right`} style={headerStyle}>
              Per call
            </th>
            <th scope="col" className={`${TH} text-right`} style={headerStyle}>
              Tokens
            </th>
            <th scope="col" className={`${TH} text-right`} style={headerStyle}>
              Failed
            </th>
            {showAgents && (
              <th scope="col" className={`${TH} text-right`} style={headerStyle}>
                Agents
              </th>
            )}
          </tr>
        </thead>
        <tbody>
          {rows.map(({ month, change }) => (
            <tr
              key={month.month}
              style={{ borderTop: "1px solid var(--line)" }}
              data-current={month.isCurrent || undefined}
            >
              <td className={`${TD} text-left`} style={{ color: "var(--ink-2)" }}>
                {formatMonth(month.month)}
                {month.isCurrent && (
                  <span
                    className="ml-2 text-[11px]"
                    style={{ color: "var(--ink-4)" }}
                  >
                    so far
                  </span>
                )}
              </td>
              <td className={`${TD} text-right`} style={{ color: "var(--ink)" }}>
                {formatSpend(month.spend)}
                {month.projectedSpend != null && (
                  <div className="text-[11px]" style={{ color: "var(--ink-4)" }}>
                    ~{formatSpend(month.projectedSpend)} projected
                  </div>
                )}
              </td>
              <td
                className={`${TD} text-right`}
                style={{ color: "var(--ink-3)" }}
                title={month.isCurrent ? "Projected month against last month" : undefined}
              >
                {formatChange(change)}
              </td>
              <td className={`${TD} text-right`} style={{ color: "var(--ink-3)" }}>
                {month.calls.toLocaleString()}
              </td>
              <td className={`${TD} text-right`} style={{ color: "var(--ink-3)" }}>
                {month.calls > 0 ? formatCallSpend(month.spend / month.calls) : "—"}
              </td>
              <td className={`${TD} text-right`} style={{ color: "var(--ink-3)" }}>
                {formatTokens(month.promptTokens + month.completionTokens)}
              </td>
              <td className={`${TD} text-right`} style={{ color: "var(--ink-3)" }}>
                {month.failedCalls.toLocaleString()}
              </td>
              {showAgents && (
                <td className={`${TD} text-right`} style={{ color: "var(--ink-3)" }}>
                  {month.activeAgents.toLocaleString()}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
