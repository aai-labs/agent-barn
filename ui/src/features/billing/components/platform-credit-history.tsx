"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { OrganizationCombobox } from "@/components/organization-combobox";
import { formatUsd } from "@/features/organizations/spend-limit";

import { formatDate, KIND_LABEL, signedUsd } from "../format";
import { usePlatformCreditHistory } from "../hooks/use-platform-credit-history";
import { CreditKindSchema, type CreditKind } from "../schemas";

const KIND_FILTER_LABEL: Record<CreditKind, string> = {
  purchase: "Purchases",
  refund: "Refunds",
  chargeback: "Disputed payments",
  adjustment: "Adjustments",
  trial: "Trial credit",
};

/** Every organization's purchases, refunds, disputed payments, adjustments and trial
 *  credit, newest first. */
export function PlatformCreditHistory() {
  const [kind, setKind] = useState<CreditKind | null>(null);
  const [organization, setOrganization] = useState<{ id: string; name: string } | null>(null);
  const { records, total, isLoading, error, refetch, hasNextPage, fetchNextPage, isFetchingNextPage } =
    usePlatformCreditHistory({ kind, organizationId: organization?.id ?? null });

  return (
    <div className="af-page">
      <div className="mb-8">
        <h1 className="m-0 text-[2rem] font-semibold tracking-[-0.025em]" style={{ color: "var(--ink)" }}>
          Billing
        </h1>
        <p className="mb-0 mt-1 text-[0.9rem]" style={{ color: "var(--ink-3)" }}>
          Credit bought, refunded and adjusted across every organization.
        </p>
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-2.5">
        <select
          aria-label="Kind"
          className="af-input"
          style={{ width: "11rem" }}
          value={kind ?? ""}
          onChange={(event) => setKind(event.target.value ? CreditKindSchema.parse(event.target.value) : null)}
        >
          <option value="">Everything</option>
          {CreditKindSchema.options.map((option) => (
            <option key={option} value={option}>
              {KIND_FILTER_LABEL[option]}
            </option>
          ))}
        </select>
        <OrganizationCombobox
          organizationId={organization?.id ?? null}
          organizationName={organization?.name ?? null}
          onChange={setOrganization}
        />
        {!isLoading && !error && (
          <span className="text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
            {total} {total === 1 ? "entry" : "entries"}
          </span>
        )}
      </div>

      {isLoading ? (
        <div className="flex items-center gap-2 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
          <Loader2 size={15} className="animate-spin" /> Loading billing…
        </div>
      ) : error ? (
        <AppErrorState error={error} title="We couldn't load billing" onRetry={() => void refetch()} />
      ) : records.length === 0 ? (
        <p className="af-card p-4 text-[0.88rem]" style={{ color: "var(--ink-2)" }}>
          Nothing here yet.
        </p>
      ) : (
        <>
          <div className="af-card overflow-x-auto">
            <table className="w-full text-[0.86rem]">
              <thead>
                <tr style={{ color: "var(--ink-4)" }}>
                  <th className="px-4 py-2 text-left font-medium">Date</th>
                  <th className="px-4 py-2 text-left font-medium">Organization</th>
                  <th className="px-4 py-2 text-left font-medium">What</th>
                  <th className="px-4 py-2 text-left font-medium">By</th>
                  <th className="px-4 py-2 text-right font-medium">Credit</th>
                  <th className="px-4 py-2 text-right font-medium">Paid</th>
                  <th className="px-4 py-2 text-left font-medium">Reference</th>
                </tr>
              </thead>
              <tbody>
                {records.map((record, index) => (
                  <tr key={`${record.createdAt}-${index}`} style={{ borderTop: "1px solid var(--line)" }}>
                    <td className="whitespace-nowrap px-4 py-2">{formatDate(record.createdAt)}</td>
                    <td className="px-4 py-2">{record.organizationName}</td>
                    <td className="px-4 py-2">{KIND_LABEL[record.kind]}</td>
                    <td className="px-4 py-2">{record.by}</td>
                    <td className="px-4 py-2 text-right tabular-nums">{signedUsd(record.creditUsd)}</td>
                    <td className="px-4 py-2 text-right tabular-nums">
                      {record.amountPaidUsd == null ? "—" : formatUsd(record.amountPaidUsd, 2)}
                    </td>
                    <td className="px-4 py-2 font-mono text-[0.8rem]" style={{ color: "var(--ink-3)" }}>
                      {record.reference ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {hasNextPage && (
            <div className="mt-4 flex justify-center">
              <button
                type="button"
                className="af-btn"
                disabled={isFetchingNextPage}
                onClick={() => void fetchNextPage()}
              >
                {isFetchingNextPage ? "Loading…" : "Load more"}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
