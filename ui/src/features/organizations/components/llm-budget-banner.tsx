"use client";

import { AlertTriangle, Ban } from "lucide-react";

import { useOrganizationLlmBudget } from "../hooks/use-organization-llm-budget";

function formatUsd(value: number, limit: number) {
  const digits = limit > 0 && limit < 1 ? 4 : 2;
  return `$${value.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

function renewalSuffix(renewsAt: string | null | undefined) {
  if (!renewsAt) return "";
  const date = new Date(renewsAt);
  if (Number.isNaN(date.getTime())) return "";
  const when = date.toLocaleDateString(undefined, { day: "numeric", month: "short" });
  return ` It resets on ${when}.`;
}

/**
 * The Organization's standing on its own spend limit.
 *
 * `show` picks which state this instance is responsible for, so the page-level
 * warning and the app-wide exhausted notice never both appear at once. Renders
 * nothing when the limit is unset, healthy, or not yet observed — an unknown figure
 * must never be presented as either safe or breached.
 */
export function LlmBudgetBanner({ show }: { show: "warning" | "exhausted" }) {
  const { budget } = useOrganizationLlmBudget();

  if (!budget || budget.state !== show) return null;
  if (budget.spendUsd == null || budget.limitUsd == null) return null;

  const exhausted = show === "exhausted";
  const used = `${formatUsd(budget.spendUsd, budget.limitUsd)} of ${formatUsd(budget.limitUsd, budget.limitUsd)}`;

  return (
    <div
      role="status"
      className="flex items-start gap-2 px-4 py-2.5 text-[13px]"
      style={{
        background: exhausted ? "var(--err-soft, #fdeaea)" : "var(--bg-soft)",
        borderBottom: "1px solid var(--line)",
        color: exhausted ? "var(--err)" : "var(--ink-2)",
      }}
    >
      {exhausted ? (
        <Ban width={15} height={15} className="mt-[1px] flex-shrink-0" />
      ) : (
        <AlertTriangle width={15} height={15} className="mt-[1px] flex-shrink-0" />
      )}
      <span>
        {exhausted
          ? `This organization has used its entire model spend allowance (${used}). Agents can't make model calls until it resets or is raised.${renewalSuffix(budget.renewsAt)}`
          : `This organization has used ${used} of its model spend allowance.${renewalSuffix(budget.renewsAt)}`}
      </span>
    </div>
  );
}
