"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { formatUsage, formatUsd, isSpendLimitQuery } from "@/features/organizations/spend-limit";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";
import { organizationLlmBudgetKey } from "@/features/organizations/utils";
import { Fact } from "@/features/spend-limits/components/fact";
import { ApiError } from "@/shared/api/error/errors";

import { takeCreditBeforeCheckout } from "../credit-before-checkout";
import { formatDate, KIND_LABEL, signedUsd } from "../format";
import { PAYMENT_WAIT_MS, useOrganizationBilling } from "../hooks/use-organization-billing";
import { BuyCreditDialog } from "./buy-credit-dialog";

type Payment = "none" | "waiting" | "arrived" | "processing" | "cancelled";

function Notice({ children }: { children: React.ReactNode }) {
  return (
    <p role="status" className="af-card mb-6 p-4 text-[0.88rem]" style={{ color: "var(--ink-2)" }}>
      {children}
    </p>
  );
}

/** The organization's credit: what's left, buying more, and every change to it. */
export function BillingPage() {
  const { selectedOrganization } = useOrganizationContext();
  const organizationId = selectedOrganization?.id;
  const router = useRouter();
  const pathname = usePathname();
  const queryClient = useQueryClient();
  const checkout = useSearchParams()?.get("checkout");
  // Read once: the address is cleaned straight away, so a reload doesn't repeat it.
  const [payment, setPayment] = useState<Payment>(() =>
    checkout === "success" ? "waiting" : checkout === "cancelled" ? "cancelled" : "none",
  );
  const { billing, isLoading, error, refetch } = useOrganizationBilling(organizationId, {
    awaitingPayment: payment === "waiting",
  });
  const [buying, setBuying] = useState(false);
  const creditBefore = useRef<number | null>(null);

  useEffect(() => {
    if (checkout && pathname) router.replace(pathname);
  }, [checkout, pathname, router]);

  useEffect(() => {
    if (payment !== "waiting") return;
    const timer = setTimeout(() => setPayment((current) => (current === "waiting" ? "processing" : current)), PAYMENT_WAIT_MS);
    return () => clearTimeout(timer);
  }, [payment]);

  useEffect(() => {
    if (!billing || payment !== "waiting") return;
    if (creditBefore.current === null) {
      // The credit before leaving to pay, when this tab kept it; otherwise this first read.
      const saved = organizationId ? takeCreditBeforeCheckout(organizationId) : null;
      creditBefore.current = saved ?? billing.creditUsd;
    }
    if (billing.creditUsd > creditBefore.current) {
      setPayment("arrived");
      // The spend limit moved with the credit: anything showing it reads again.
      void queryClient.invalidateQueries({ queryKey: organizationLlmBudgetKey.all });
      void queryClient.invalidateQueries({ predicate: (query) => isSpendLimitQuery(query.queryKey) });
    }
  }, [billing, payment, queryClient, organizationId]);

  const forbidden = error instanceof ApiError && error.status === 403;

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

      {payment === "waiting" && <Notice>Payment received. Your credit will appear here within a minute.</Notice>}
      {payment === "arrived" && <Notice>Your credit has been added.</Notice>}
      {payment === "processing" && (
        <Notice>
          Your payment is still being processed. Some payment methods take a few days; your credit appears here once
          it clears.
        </Notice>
      )}
      {payment === "cancelled" && <Notice>Payment cancelled. Nothing was charged.</Notice>}

      {isLoading ? (
        <div className="flex items-center gap-2 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
          <Loader2 size={15} className="animate-spin" /> Loading billing…
        </div>
      ) : forbidden ? (
        <p className="af-card p-4 text-[0.88rem]" style={{ color: "var(--ink-2)" }}>
          You don&apos;t have access to this organization&apos;s billing.
        </p>
      ) : error || !billing ? (
        <AppErrorState error={error} title="We couldn't load billing" onRetry={() => void refetch()} />
      ) : (
        <>
          {!billing.onCredit ? (
            <p className="af-card mb-9 p-4 text-[0.88rem]" style={{ color: "var(--ink-2)" }}>
              This organization&apos;s spend is covered by its plan, so it doesn&apos;t buy credit.
            </p>
          ) : (
            <>
              {!billing.available && (
                <p className="af-card mb-6 p-4 text-[0.88rem]" style={{ color: "var(--ink-2)" }}>
                  Buying credit isn&apos;t available right now.
                </p>
              )}
              <section className="af-card mb-9 p-5" aria-label="Balance">
                <dl className="m-0 grid gap-x-8 gap-y-4 sm:grid-cols-3">
                  <Fact label="Balance">
                    {billing.balanceUsd == null ? (
                      <span className="text-[1.4rem] font-semibold">Not available yet</span>
                    ) : (
                      <span
                        className="text-[1.4rem] font-semibold"
                        style={{ color: billing.balanceUsd <= 0 ? "var(--err)" : "var(--ink)" }}
                      >
                        {formatUsd(billing.balanceUsd, 2)}
                        {billing.balanceUsd <= 0 && <span className="ml-2 text-[0.86rem] font-medium">Used up</span>}
                      </span>
                    )}
                  </Fact>
                  <Fact label="Used">
                    {billing.spendUsd == null
                      ? "Not available yet"
                      : `${formatUsage(billing.spendUsd, billing.creditUsd)} used`}
                  </Fact>
                  <Fact label="Credit added">{formatUsd(billing.creditUsd, 2)}</Fact>
                </dl>
              </section>
            </>
          )}

          <h2 className="mb-3 text-[16px] font-semibold" style={{ color: "var(--ink)" }}>
            History
          </h2>
          {billing.history.length === 0 ? (
            <p className="af-card p-4 text-[0.88rem]" style={{ color: "var(--ink-3)" }}>
              No credit added yet.
            </p>
          ) : (
            <div className="af-card overflow-x-auto">
              <table className="w-full text-[0.86rem]">
                <thead>
                  <tr style={{ color: "var(--ink-4)" }}>
                    <th className="px-4 py-2 text-left font-medium">Date</th>
                    <th className="px-4 py-2 text-left font-medium">What</th>
                    <th className="px-4 py-2 text-left font-medium">By</th>
                    <th className="px-4 py-2 text-right font-medium">Credit</th>
                    <th className="px-4 py-2 text-right font-medium">Paid</th>
                  </tr>
                </thead>
                <tbody>
                  {billing.history.map((item, index) => (
                    <tr key={`${item.createdAt}-${index}`} style={{ borderTop: "1px solid var(--line)" }}>
                      <td className="px-4 py-2">{formatDate(item.createdAt)}</td>
                      <td className="px-4 py-2">{KIND_LABEL[item.kind]}</td>
                      <td className="px-4 py-2">{item.purchasedBy ?? "—"}</td>
                      <td className="px-4 py-2 text-right tabular-nums">{signedUsd(item.creditUsd)}</td>
                      <td className="px-4 py-2 text-right tabular-nums">
                        {item.amountPaidUsd == null ? "—" : formatUsd(item.amountPaidUsd, 2)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

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
