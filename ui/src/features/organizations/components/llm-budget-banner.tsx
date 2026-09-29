"use client";

import Link from "next/link";
import { AlertTriangle, Ban } from "lucide-react";

import { useActiveOrgRole } from "../hooks/use-active-org-role";
import { useOrganizationLlmBudget } from "../hooks/use-organization-llm-budget";
import { formatRenewal, formatUsage, periodLabel } from "../spend-limit";


function renewalSuffix(renewsAt: string | null | undefined) {
  return renewsAt ? ` It renews on ${formatRenewal(renewsAt)}.` : "";
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
  const { selectedOrganization } = useActiveOrgRole();

  if (!budget || budget.state !== show) return null;
  if (budget.spendUsd == null) return null;

  const exhausted = show === "exhausted";
  const used = formatUsage(budget.spendUsd, budget.limitUsd);

  return (
    <div
      role="status"
      className="flex items-start gap-2 px-4 py-2.5 text-[13px]"
      style={{
        background: exhausted ? "var(--err-soft)" : "var(--bg-soft)",
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
          ? `This organization has reached its model spend limit (${used}). Agents can't make model calls until it renews or is raised.${renewalSuffix(budget.renewsAt)}`
          : `This organization has used ${used} of its model spend limit ${periodLabel(budget.window)}.${renewalSuffix(budget.renewsAt)}`}
      </span>
      {exhausted && budget.canManage && selectedOrganization && (
        <Link
          href={`/dashboard/${selectedOrganization.id}/settings?tab=spend-limits`}
          className="ml-auto flex-shrink-0 font-medium underline underline-offset-2"
        >
          Raise limit
        </Link>
      )}
    </div>
  );
}
