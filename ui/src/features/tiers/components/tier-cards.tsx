import type { ReactNode } from "react";
import { Check } from "lucide-react";

import { Badge } from "@/components/badge";

import { formatUsd } from "@/features/organizations/spend-limit";

import type { PublicTier } from "../schemas";
import { describeUsage, TIER_FEATURES } from "../utils";

/** The offered tiers side by side, each with what it includes and the caller's action. */
export function TierCards({
  tiers,
  currentKey,
  action,
}: {
  tiers: PublicTier[];
  currentKey?: string | null;
  action: (tier: PublicTier) => ReactNode;
}) {
  return (
    // As many columns as fit the space it is given: four on the Billing page, two in onboarding.
    <ul
      className="m-0 grid list-none gap-3 p-0"
      style={{ gridTemplateColumns: "repeat(auto-fill, minmax(min(100%, 15rem), 1fr))" }}
      aria-label="Tiers"
    >
      {tiers.map((tier) => {
        const included = TIER_FEATURES.filter((feature) => tier.features.includes(feature.key));
        return (
          <li
            key={tier.key}
            aria-label={tier.name}
            className="flex flex-col gap-3 rounded-xl border p-5"
            style={{
              borderColor: tier.key === currentKey ? "var(--ink)" : "var(--line)",
              background: "var(--bg-elev)",
            }}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-semibold">{tier.name}</span>
              {tier.key === currentKey && <Badge>Current</Badge>}
            </div>
            <div>
              <div className="flex flex-wrap items-baseline gap-x-1.5">
                <span className="text-[1.25rem] font-semibold">{formatUsd(Number(tier.priceUsd), Number(tier.priceUsd) % 1 ? 2 : 0)}</span>
                {tier.priceNote && (
                  <span className="text-[0.82rem]" style={{ color: "var(--ink-3)" }}>
                    {tier.priceNote}
                  </span>
                )}
              </div>
              {tier.tagline && (
                <p className="mb-0 mt-1 text-[0.82rem]" style={{ color: "var(--ink-3)" }}>
                  {tier.tagline}
                </p>
              )}
            </div>
            <ul className="m-0 flex list-none flex-col gap-1.5 p-0 text-[0.82rem]" style={{ color: "var(--ink-2)" }}>
              <li>Usage: {describeUsage(tier)}</li>
              <li>
                {tier.agentLimit} {tier.agentLimit === 1 ? "agent" : "agents"}
              </li>
              {included.map((feature) => (
                <li key={feature.key} className="flex items-start gap-1.5">
                  <Check size={13} className="mt-[3px] shrink-0" aria-hidden /> {feature.label}
                </li>
              ))}
            </ul>
            <div className="mt-auto">{action(tier)}</div>
          </li>
        );
      })}
    </ul>
  );
}
