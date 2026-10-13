"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";
import { Loader2 } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { formatUsage, formatUsd } from "@/features/organizations/spend-limit";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";
import { Fact } from "@/features/spend-limits/components/fact";

import { useOrganizationBilling } from "../hooks/use-organization-billing";
import type { CreditHistoryItem } from "../schemas";
import { BuyCreditDialog } from "./buy-credit-dialog";

const KIND_LABEL: Record<CreditHistoryItem["kind"], string> = {
  trial: "Trial credit",
  purchase: "Purchase",
  refund: "Refund",
  chargeback: "Disputed payment",
  adjustment: "Adjustment",
};

function formatDate(iso: string) {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

function signedUsd(value: number) {
  return `${value < 0 ? "−" : "+"}${formatUsd(Math.abs(value), 2)}`;
}

/** The organization's credit: what's left, buying more, and every change to it. */
export function BillingPage() {
  const { selectedOrganization } = useOrganizationContext();
  const organizationId = selectedOrganization?.id;
  const checkout = useSearchParams()?.get("checkout");
  const { billing, isLoading, error, refetch } = useOrganizationBilling(organizationId, {
    awaitingPayment: checkout === "success",
  });
  const [buying, setBuying] = useState(false);

  return (
    <div className="af-page">
      <div className="mb-8 flex flex-wrap items-start gap-4">
        <div className="min-w-0 flex-1">
          <h1 className="m-0 text-[2rem] font-semibold tracking-[-0.025em]" style={{ color: "var(--ink)" }}>
            Billing
          </h1>
          <p className="mb-0 mt-1 text-[0.9rem]" style={{ color: "var(--ink-3)" }}>
            Credit your agents spend on model calls.
          </p>
        </div>
        {billing?.available && (
          <button type="button" className="af-btn af-btn-primary" onClick={() => setBuying(true)}>
            Buy credit
          </button>
        )}
      </div>

      {checkout === "success" && (
        <p role="status" className="af-card mb-6 p-4 text-[0.88rem]" style={{ color: "var(--ink-2)" }}>
          Payment received. Your credit will appear here within a minute.
        </p>
      )}
      {checkout === "cancelled" && (
        <p role="status" className="af-card mb-6 p-4 text-[0.88rem]" style={{ color: "var(--ink-2)" }}>
          Payment cancelled. Nothing was charged.
        </p>
      )}

      {isLoading ? (
        <div className="flex items-center gap-2 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
          <Loader2 size={15} className="animate-spin" /> Loading billing…
        </div>
      ) : error || !billing ? (
        <AppErrorState error={error} title="We couldn't load billing" onRetry={() => void refetch()} />
      ) : (
        <>
          {!billing.available && (
            <p className="af-card mb-6 p-4 text-[0.88rem]" style={{ color: "var(--ink-2)" }}>
              Buying credit isn&apos;t available for this organization.
            </p>
          )}
          <section className="af-card mb-9 p-5" aria-label="Balance">
            <dl className="m-0 grid gap-x-8 gap-y-4 sm:grid-cols-3">
              <Fact label="Balance">
                <span
                  className="text-[1.4rem] font-semibold"
                  style={{
                    color: billing.balanceUsd != null && billing.balanceUsd <= 0 ? "var(--err)" : "var(--ink)",
                  }}
                >
                  {billing.balanceUsd == null ? "Not available yet" : formatUsd(billing.balanceUsd, 2)}
                </span>
              </Fact>
              <Fact label="Used">
                {billing.spendUsd == null ? "Not available yet" : `${formatUsage(billing.spendUsd, billing.creditUsd)} used`}
              </Fact>
              <Fact label="Credit added">{formatUsd(billing.creditUsd, 2)}</Fact>
            </dl>
          </section>

          <h2 className="mb-3 text-[16px] font-semibold" style={{ color: "var(--ink)" }}>
            History
          </h2>
          <div className="af-card overflow-x-auto">
            <table className="w-full text-[0.86rem]">
              <thead>
                <tr style={{ color: "var(--ink-4)" }}>
                  <th className="px-4 py-2 text-left font-medium">Date</th>
                  <th className="px-4 py-2 text-left font-medium">What</th>
                  <th className="px-4 py-2 text-right font-medium">Credit</th>
                  <th className="px-4 py-2 text-right font-medium">Paid</th>
                </tr>
              </thead>
              <tbody>
                {billing.history.map((item, index) => (
                  <tr key={`${item.createdAt}-${index}`} style={{ borderTop: "1px solid var(--line)" }}>
                    <td className="px-4 py-2">{formatDate(item.createdAt)}</td>
                    <td className="px-4 py-2">{KIND_LABEL[item.kind]}</td>
                    <td className="px-4 py-2 text-right tabular-nums">{signedUsd(item.creditUsd)}</td>
                    <td className="px-4 py-2 text-right tabular-nums">
                      {item.amountPaidUsd == null ? "—" : formatUsd(item.amountPaidUsd, 2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {organizationId && (
            <BuyCreditDialog
              organizationId={organizationId}
              billing={billing}
              open={buying}
              onOpenChange={setBuying}
            />
          )}
        </>
      )}
    </div>
  );
}
