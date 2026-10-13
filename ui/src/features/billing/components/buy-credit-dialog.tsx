"use client";

import { useState } from "react";

import { ConfirmationDialog } from "@/components/confirmation-dialog";
import { formatUsd, parseAmount } from "@/features/organizations/spend-limit";
import { MoneyInput } from "@/features/spend-limits/components/money-input";
import { getErrorDisplay } from "@/shared/api/error/get-error-display";

import { useStartCheckout } from "../hooks/use-organization-billing";
import { chargeUsd } from "../pricing";
import type { OrganizationBilling } from "../schemas";

/** Choose how much credit to add, see what it costs, and go to the payment page. */
export function BuyCreditDialog({
  organizationId,
  billing,
  open,
  onOpenChange,
}: {
  organizationId: string;
  billing: OrganizationBilling;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [amount, setAmount] = useState("");
  const checkout = useStartCheckout(organizationId);
  const parsed = parseAmount(amount);
  const inBounds =
    parsed !== null &&
    !Number.isNaN(parsed) &&
    parsed >= billing.minPurchaseUsd &&
    parsed <= billing.maxPurchaseUsd &&
    // Cents at most: the API refuses anything finer.
    Math.round(parsed * 100) === parsed * 100;
  const error =
    amount.trim() === "" || inBounds
      ? null
      : `Choose between ${formatUsd(billing.minPurchaseUsd, 2)} and ${formatUsd(billing.maxPurchaseUsd, 2)}.`;

  return (
    <ConfirmationDialog
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          setAmount("");
          checkout.reset();
        }
        onOpenChange(next);
      }}
      title="Buy credit"
      description="Your agents spend credit on model calls. It never expires."
      confirmLabel="Continue to payment"
      pendingLabel="Opening payment…"
      isPending={checkout.isPending}
      confirmDisabled={!inBounds}
      onConfirm={async () => {
        if (!inBounds || parsed === null) return;
        try {
          const { url } = await checkout.mutateAsync(parsed);
          window.location.assign(url);
        } catch {
          /* The error stays in the dialog. */
        }
      }}
    >
      <div className="flex flex-col gap-3">
        <MoneyInput
          label="Credit to add"
          value={amount}
          onChange={setAmount}
          placeholder="20"
          error={error}
          hint={`Between ${formatUsd(billing.minPurchaseUsd, 2)} and ${formatUsd(billing.maxPurchaseUsd, 2)}.`}
        />
        {inBounds && parsed !== null && (
          <p className="m-0 text-[0.88rem]" style={{ color: "var(--ink-2)" }}>
            You&apos;ll pay {formatUsd(chargeUsd(parsed, billing), 2)}
            {billing.purchaseFeePercent > 0 ? `, including a ${billing.purchaseFeePercent}% purchase fee` : ""}.
            You&apos;ll finish paying on a secure payment page.
          </p>
        )}
        {checkout.isError && (
          <p className="m-0 text-[13px]" role="alert" style={{ color: "var(--err)" }}>
            {getErrorDisplay(checkout.error).description}
          </p>
        )}
      </div>
    </ConfirmationDialog>
  );
}
