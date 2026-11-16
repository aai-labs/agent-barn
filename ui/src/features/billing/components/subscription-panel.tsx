"use client";

import { useState } from "react";

import { ConfirmationDialog } from "@/components/confirmation-dialog";
import { formatUsd } from "@/features/organizations/spend-limit";
import { TierCards } from "@/features/tiers/components/tier-cards";
import { useOfferedTiers } from "@/features/tiers/hooks/use-offered-tiers";
import type { PublicTier } from "@/features/tiers/schemas";
import { getErrorDisplay } from "@/shared/api/error/get-error-display";
import { toastError } from "@/shared/toast";

import { formatDate } from "../format";
import { useSubscriptionActions } from "../hooks/use-subscription-actions";
import type { OrganizationBilling } from "../schemas";
import { HoldPreview } from "./hold-preview";

/** The organization's tier and subscription, and the tiers it can move to. */
export function SubscriptionPanel({
  organizationId,
  billing,
}: {
  organizationId: string;
  billing: OrganizationBilling;
}) {
  const { tiers } = useOfferedTiers();
  const { subscribe, setCancel, openPortal } = useSubscriptionActions(organizationId);
  const [chosen, setChosen] = useState<PublicTier | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const subscription = billing.subscription ?? null;
  const currentKey = billing.tier?.key ?? null;
  const demo = (subscription?.provider ?? billing.subscriptionProvider) === "mock";
  const stripe = (subscription?.provider ?? billing.subscriptionProvider) === "stripe";
  const scheduled = subscription?.scheduledTier ?? null;
  const priceOf = (key: string | null | undefined) => Number(tiers.find((tier) => tier.key === key)?.priceUsd ?? 0);
  // A bigger tier applies at once; a smaller one waits for the renewal.
  const downgrade = (tier: PublicTier) => !!subscription && Number(tier.priceUsd) < priceOf(currentKey);

  const describeChange = (tier: PublicTier) => {
    const cost = `${tier.name} costs ${formatUsd(Number(tier.priceUsd), 2)} ${tier.priceNote ?? ""}.`;
    if (!subscription) return stripe ? `${cost} You'll pay on Stripe's secure page.` : `${cost} It applies straight away.`;
    if (downgrade(tier)) {
      return `${cost} You keep ${subscription.tier.name} until ${formatDate(subscription.currentPeriodEnd)}, then move to ${tier.name}.`;
    }
    return stripe
      ? `${cost} It applies straight away, and you're charged for the rest of this month now.`
      : `${cost} It applies straight away.`;
  };

  const tierAction = (tier: PublicTier) => {
    if (tier.key === currentKey) return null;
    if (tier.activation === "contact") {
      return tier.contactUrl ? (
        <a className="af-btn w-full justify-center" href={tier.contactUrl} target="_blank" rel="noreferrer">
          Book a call
        </a>
      ) : null;
    }
    if (tier.activation !== "paid" || !billing.subscriptionsAvailable) return null;
    if (scheduled?.key === tier.key) {
      return (
        <button type="button" className="af-btn w-full justify-center" disabled>
          From {formatDate(subscription?.currentPeriodEnd ?? "")}
        </button>
      );
    }
    return (
      <button
        type="button"
        className="af-btn af-btn-primary w-full justify-center"
        aria-label={subscription ? `Switch to ${tier.name}` : `Subscribe to ${tier.name}`}
        onClick={() => setChosen(tier)}
      >
        {subscription ? "Switch" : "Subscribe"}
      </button>
    );
  };

  return (
    <section className="mb-9" aria-label="Tier">
      <div className="af-card mb-4 p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="m-0 text-[15px] font-semibold" style={{ color: "var(--ink)" }}>
              {billing.tier ? billing.tier.name : "No tier"}
            </h2>
            <p className="mb-0 mt-1 text-[0.86rem]" style={{ color: "var(--ink-3)" }}>
              {subscription
                ? subscription.cancelAtPeriodEnd
                  ? `Ends on ${formatDate(subscription.currentPeriodEnd)}, then your organization moves to Free and keeps its credit.`
                  : subscription.status === "past_due"
                    ? `${formatUsd(subscription.allowanceRemainingUsd, 2)} of this month's ${formatUsd(subscription.allowanceUsd, 2)} usage left.`
                    : scheduled
                    ? `Moves to ${scheduled.name} on ${formatDate(subscription.currentPeriodEnd)}. Until then you keep ${subscription.tier.name}. ${formatUsd(subscription.allowanceRemainingUsd, 2)} of this month's ${formatUsd(subscription.allowanceUsd, 2)} usage left.`
                    : `Renews on ${formatDate(subscription.currentPeriodEnd)}. ${formatUsd(subscription.allowanceRemainingUsd, 2)} of this month's ${formatUsd(subscription.allowanceUsd, 2)} usage left.`
                : billing.tierAssignedByPlatform
                  ? "Set by a platform administrator."
                  : billing.upgradeRequired
                    ? "Subscribe to a paid tier for monthly usage, more agents, and to buy credit."
                    : null}
            </p>
            {subscription?.status === "past_due" && (
              <p role="alert" className="mb-0 mt-2 text-[0.86rem]" style={{ color: "var(--warn)" }}>
                Your last payment failed.{" "}
                {subscription.graceEndsAt
                  ? `Update your card by ${formatDate(subscription.graceEndsAt)} to keep ${subscription.tier.name}.`
                  : `Update your card to keep ${subscription.tier.name}.`}
              </p>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            {subscription?.manageable && (
              <button
                type="button"
                className="af-btn"
                disabled={openPortal.isPending}
                onClick={() => void openPortal.mutateAsync().catch(toastError)}
              >
                {openPortal.isPending ? "Opening…" : "Manage payment"}
              </button>
            )}
            {subscription && scheduled && !subscription.cancelAtPeriodEnd && (
              <button
                type="button"
                className="af-btn"
                disabled={subscribe.isPending}
                onClick={() => void subscribe.mutateAsync(subscription.tier.key).catch(toastError)}
              >
                Keep {subscription.tier.name}
              </button>
            )}
            {subscription && (
              <button
                type="button"
                className="af-btn"
                disabled={setCancel.isPending}
                onClick={() =>
                  subscription.cancelAtPeriodEnd
                    ? void setCancel.mutateAsync(false).catch(toastError)
                    : setCancelling(true)
                }
              >
                {subscription.cancelAtPeriodEnd ? "Keep subscription" : "Cancel subscription"}
              </button>
            )}
          </div>
        </div>
        {demo && (
          <p className="mb-0 mt-3 text-[0.8rem]" style={{ color: "var(--ink-4)" }}>
            Demo payments: subscribing here charges nothing.
          </p>
        )}
      </div>
      {tiers.length > 0 && <TierCards tiers={tiers} currentKey={currentKey} action={tierAction} />}
      <ConfirmationDialog
        open={chosen !== null}
        onOpenChange={(open) => !open && setChosen(null)}
        title={chosen ? `${subscription ? "Switch" : "Subscribe"} to ${chosen.name}?` : ""}
        description={chosen ? describeChange(chosen) : ""}
        confirmLabel={subscription ? "Switch" : stripe ? "Continue to payment" : "Subscribe"}
        pendingLabel="Saving…"
        isPending={subscribe.isPending}
        onConfirm={async () => {
          if (!chosen) return;
          try {
            await subscribe.mutateAsync(chosen.key);
            setChosen(null);
          } catch {
            /* The error stays in the dialog. */
          }
        }}
      >
        {/* Switching can lower what the organization may run; subscribing from Free or no tier can't. */}
        {subscription && <HoldPreview organizationId={organizationId} tierKey={chosen?.key ?? null} />}
        {subscribe.isError && (
          <p className="m-0 text-[13px]" role="alert" style={{ color: "var(--err)" }}>
            {getErrorDisplay(subscribe.error).description}
          </p>
        )}
      </ConfirmationDialog>
      {subscription && (
        <ConfirmationDialog
          open={cancelling}
          onOpenChange={setCancelling}
          title="Cancel your subscription?"
          description={`It ends on ${formatDate(subscription.currentPeriodEnd)}. Your organization then moves to Free and keeps its credit. You can keep the subscription until then.`}
          confirmLabel="Cancel subscription"
          cancelLabel="Keep subscription"
          pendingLabel="Cancelling…"
          variant="destructive"
          isPending={setCancel.isPending}
          onConfirm={async () => {
            try {
              await setCancel.mutateAsync(true);
              setCancelling(false);
            } catch {
              /* The error stays in the dialog. */
            }
          }}
        >
          <HoldPreview organizationId={organizationId} tierKey={cancelling ? "free" : null} />
          {setCancel.isError && (
            <p className="m-0 text-[13px]" role="alert" style={{ color: "var(--err)" }}>
              {getErrorDisplay(setCancel.error).description}
            </p>
          )}
        </ConfirmationDialog>
      )}
    </section>
  );
}
