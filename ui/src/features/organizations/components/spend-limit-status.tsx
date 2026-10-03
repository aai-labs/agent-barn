"use client";

import Link from "next/link";
import { ArrowRight, Wallet } from "lucide-react";

import { useOrganizationLlmBudget } from "../hooks/use-organization-llm-budget";
import { useActiveOrgRole } from "../hooks/use-active-org-role";
import { formatRenewal, formatUsage, formatUsd, periodLabel, usdDigits, windowLabel } from "../spend-limit";

/**
 * Where the organization stands against its model spend limit, on the Costs page.
 * Read-only: limits are changed in Settings → Spend limits, where every level can be
 * seen together.
 */
export function SpendLimitStatus() {
  const { budget, isLoading, error } = useOrganizationLlmBudget();
  const { selectedOrganization } = useActiveOrgRole();

  if (isLoading) {
    return <div className="af-card mb-6 h-[52px] animate-pulse" aria-hidden style={{ background: "var(--bg-soft)" }} />;
  }
  if (error || !budget) {
    return (
      <p className="m-0 mb-6 text-[13px]" role="status" style={{ color: "var(--ink-3)" }}>
        Your spend limit couldn&apos;t be loaded right now.
      </p>
    );
  }

  const exhausted = budget.state === "exhausted";
  const usage =
    budget.spendUsd == null
      ? `${formatUsd(budget.limitUsd, usdDigits(budget.limitUsd))} ${windowLabel(budget.window)} · spend not available yet`
      : `${formatUsage(budget.spendUsd, budget.limitUsd)} used ${periodLabel(budget.window)}`;

  return (
    <section
      aria-label="Model spend limit"
      className="af-card mb-6 flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 text-[13px]"
    >
      <span className="flex items-center gap-2 font-semibold" style={{ color: "var(--ink)" }}>
        <Wallet width={15} height={15} aria-hidden /> Model spend limit
      </span>
      <span style={{ color: exhausted ? "var(--err)" : "var(--ink-2)" }}>
        {usage}
        {exhausted ? " — limit reached" : ""}
      </span>
      {budget.renewsAt && (
        <span style={{ color: "var(--ink-3)" }}>Renews {formatRenewal(budget.renewsAt)}</span>
      )}
      {budget.canManage && selectedOrganization && (
        <Link
          href={`/dashboard/${selectedOrganization.id}/settings?tab=spend-limits`}
          className="ml-auto inline-flex items-center gap-1 font-medium underline-offset-2 hover:underline"
          style={{ color: "var(--ink)" }}
        >
          Manage limits <ArrowRight size={14} aria-hidden />
        </Link>
      )}
    </section>
  );
}
