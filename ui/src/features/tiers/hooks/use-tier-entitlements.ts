"use client";

import { useOrganization } from "@/features/organizations/hooks/use-organization";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";

export type TierFeatureKey =
  | "custom_agents"
  | "integrations"
  | "templates_and_skills"
  | "workflows"
  | "agent_webhooks"
  | "agent_memory"
  | "team"
  | "priority_support";

/**
 * What the selected organization's tier lets it use. Until the organization read arrives,
 * or without a tier, everything is allowed: the API refuses what the tier leaves out, so
 * the UI only hides what would be refused.
 */
export function useTierEntitlements() {
  const { selectedOrganization } = useOrganizationContext();
  const { organization } = useOrganization(selectedOrganization?.id ?? "");
  const entitlements = organization?.entitlements ?? null;

  return {
    tier: organization?.tier ?? null,
    overTier: organization?.overTier ?? false,
    hasFeature: (feature: TierFeatureKey) => !entitlements || entitlements.features.includes(feature),
    allowsPlatform: (platformKey: string) =>
      !entitlements || entitlements.allowedPlatformKeys === null || entitlements.allowedPlatformKeys.includes(platformKey),
  };
}
