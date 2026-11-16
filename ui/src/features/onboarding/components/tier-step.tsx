"use client";

import { TierCards } from "@/features/tiers/components/tier-cards";
import type { PublicTier } from "@/features/tiers/schemas";

/** The body of the tier step: every offered tier, with the way to get each from here. */
export function TierStep({
  tiers,
  currentKey,
  requestedKey,
  canSubscribe,
  subscribingKey,
  onContinue,
  onSubscribe,
}: {
  tiers: PublicTier[];
  // The tier the organization is on now: Free for a new trial, none for a returning inbox.
  currentKey: string | null;
  // The tier picked on the pricing page, if any.
  requestedKey: string | null;
  canSubscribe: boolean;
  subscribingKey: string | null;
  onContinue: () => void;
  onSubscribe: (tier: PublicTier) => void;
}) {
  const requested = tiers.find((tier) => tier.key === requestedKey && tier.key !== currentKey);
  return (
    <>
      {requested && (
        <p className="mb-4 mt-0 text-[0.9rem]" style={{ color: "var(--ink-2)" }}>
          You picked {requested.name} on our pricing page.
        </p>
      )}
      <TierCards
        tiers={tiers}
        currentKey={currentKey}
        action={(tier) => {
          if (tier.key === currentKey) {
            return (
              <button
                type="button"
                className="af-btn w-full justify-center"
                aria-label={`Continue with ${tier.name}`}
                onClick={onContinue}
              >
                Continue
              </button>
            );
          }
          if (tier.activation === "contact" && tier.contactUrl) {
            return (
              <a className="af-btn w-full justify-center" href={tier.contactUrl} target="_blank" rel="noreferrer">
                Book a call
              </a>
            );
          }
          if (tier.activation === "paid" && canSubscribe) {
            return (
              <button
                type="button"
                className={`af-btn w-full justify-center${tier.key === requestedKey ? " af-btn-primary" : ""}`}
                disabled={subscribingKey !== null}
                aria-label={`Subscribe to ${tier.name}`}
                onClick={() => onSubscribe(tier)}
              >
                {subscribingKey === tier.key ? "Subscribing…" : "Subscribe"}
              </button>
            );
          }
          return null;
        }}
      />
      {canSubscribe && (
        <p className="mb-0 mt-3 text-[0.8rem]" style={{ color: "var(--ink-4)" }}>
          Demo payments: subscribing here charges nothing.
        </p>
      )}
    </>
  );
}
