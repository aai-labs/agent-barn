"use client";

import { useState } from "react";

import { Badge } from "@/components/badge";
import { ConfirmationDialog } from "@/components/confirmation-dialog";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useTiers } from "@/features/tiers/hooks/use-tiers";
import { getErrorDisplay } from "@/shared/api/error/get-error-display";
import { toastError } from "@/shared/toast";

import { usePlatformSubscription } from "../hooks/use-platform-subscription";
import { useSetOrganizationTier } from "../hooks/use-set-organization-tier";
import type { PlatformOrganization } from "../schemas";

const NO_TIER = "no-tier";

/** The tier an organization is on, and the Platform Administrator's way to change it. */
export function TierCard({ organization }: { organization: PlatformOrganization }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(NO_TIER);
  const { tiers, isLoadingTiers, tiersError } = useTiers();
  const setTier = useSetOrganizationTier(organization.id);
  const { subscription, endPeriod } = usePlatformSubscription(organization.id);

  return (
    <section className="af-card mb-9 p-5" aria-label="Tier">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <h2 className="m-0 flex items-center gap-2 text-[15px] font-semibold" style={{ color: "var(--ink)" }}>
            Tier
            {organization.overTier && <Badge variant="warn">Over its tier</Badge>}
          </h2>
          <p className="mb-0 mt-1 text-[13.5px] leading-relaxed" style={{ color: "var(--ink-3)" }}>
            {organization.tier ? organization.tier.name : "No tier: platform-managed, with nothing restricted"}
            {subscription &&
              ` · ${subscription.provider === "mock" ? "Demo subscription" : "Subscription"}, ${
                subscription.cancelAtPeriodEnd ? "ends" : "renews"
              } ${new Date(subscription.currentPeriodEnd).toLocaleDateString()}`}
          </p>
        </div>
        {/* Only a demo subscription's period can end early; a payment provider renews the rest. */}
        {subscription?.provider === "mock" && (
          <button
            type="button"
            className="af-btn"
            disabled={endPeriod.isPending}
            title="Expire this period's unused usage now, then renew or end the subscription."
            onClick={() => void endPeriod.mutateAsync().catch(toastError)}
          >
            {endPeriod.isPending ? "Ending period…" : "End period now"}
          </button>
        )}
        <button
          type="button"
          className="af-btn"
          disabled={isLoadingTiers || Boolean(tiersError)}
          onClick={() => {
            setValue(organization.tierId ?? NO_TIER);
            setTier.reset();
            setEditing(true);
          }}
        >
          Change
        </button>
      </div>
      <ConfirmationDialog
        open={editing}
        onOpenChange={setEditing}
        title={`Which tier is ${organization.name} on?`}
        description="What it already runs is kept. A lower tier only stops new use of what it leaves out."
        confirmLabel="Save"
        pendingLabel="Saving…"
        isPending={setTier.isPending}
        onConfirm={async () => {
          try {
            await setTier.mutateAsync(value === NO_TIER ? null : value);
            setEditing(false);
          } catch {
            /* The error stays in the dialog. */
          }
        }}
      >
        <Select value={value} onValueChange={setValue}>
          <SelectTrigger aria-label="Tier" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem value={NO_TIER}>No tier (platform-managed)</SelectItem>
              {tiers.map((tier) => (
                <SelectItem key={tier.id} value={tier.id}>
                  {tier.enabled || tier.activation === "none" ? tier.name : `${tier.name} (not offered)`}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        {setTier.isError && (
          <p className="mb-0 mt-3 text-[13px]" role="alert" style={{ color: "var(--err)" }}>
            {getErrorDisplay(setTier.error).description}
          </p>
        )}
      </ConfirmationDialog>
    </section>
  );
}
