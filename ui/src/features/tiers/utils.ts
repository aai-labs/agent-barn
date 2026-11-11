import { formatUsd } from "@/features/organizations/spend-limit";

import type { Tier, TierActivation } from "./schemas";

export const tiersKey = {
  /** Platform data: no Organization's cache is its. */
  platform: ["platform", "tiers"] as const,
};

// The API's bounds, so the dialog refuses what the API would.
export const MAX_AMOUNT_USD = 100_000;
export const MAX_AGENT_LIMIT = 1_000;

export const ACTIVATION_LABELS: Record<TierActivation, string> = {
  free: "Free at sign-up",
  paid: "Monthly subscription",
  contact: "Contact only",
  none: "System",
};

/** The features a tier may allow, in the API's order. Platforms are chosen separately. */
export const TIER_FEATURES = [
  { key: "custom_agents", label: "Custom agents", help: "Build agents from any template, not only the premade one." },
  { key: "integrations", label: "Integrations", help: "Connect Jira, GitHub, Gmail and other services." },
  { key: "templates_and_skills", label: "Templates & skills", help: "Manage the organization's templates and skills." },
  { key: "workflows", label: "Workflows", help: "Author and run workflows and schedules." },
  { key: "agent_webhooks", label: "Agent webhooks", help: "Let other systems hand work to an agent." },
  { key: "agent_memory", label: "Agent Memory", help: "Long-term memory shared through Agent Barn." },
  { key: "team", label: "Team", help: "Invite members and give them access to agents." },
  { key: "priority_support", label: "Priority support", help: "Shown to customers; nothing in the product changes." },
] as const;

/** The platforms an agent may be reached on, in the API's order. */
export const TIER_PLATFORMS = [
  { key: "slack", label: "Slack" },
  { key: "teams", label: "Microsoft Teams" },
  { key: "telegram", label: "Telegram (own bot)" },
  { key: "agentbarn_telegram", label: "Telegram (Agent Barn bot)" },
  { key: "discord", label: "Discord" },
  { key: "web", label: "Web Chat" },
  { key: "email", label: "Email" },
] as const;

/** "$20.00 per month", "Free", or a contact-only tier's informational price. */
export function describePrice(tier: Pick<Tier, "priceUsd" | "priceNote" | "activation">): string {
  const price = Number(tier.priceUsd);
  if (price === 0 && tier.activation !== "contact") return "Free";
  const amount = formatUsd(price, 2);
  return tier.priceNote ? `${amount} ${tier.priceNote}` : amount;
}

/** "$20.00 monthly + $10.00 once", or "None". */
export function describeUsage(tier: Pick<Tier, "monthlyUsageUsd" | "oneTimeCreditUsd">): string {
  const monthly = Number(tier.monthlyUsageUsd);
  const once = Number(tier.oneTimeCreditUsd);
  const parts = [
    ...(monthly > 0 ? [`${formatUsd(monthly, 2)} monthly`] : []),
    ...(once > 0 ? [`${formatUsd(once, 2)} once`] : []),
  ];
  return parts.length ? parts.join(" + ") : "None";
}

export function describePlatforms(keys: string[] | null): string {
  if (keys === null) return "Every platform";
  if (keys.length === 0) return "None";
  return keys.map((key) => TIER_PLATFORMS.find((platform) => platform.key === key)?.label ?? key).join(", ");
}

export function describeFeatures(keys: string[]): string {
  if (keys.length === 0) return "None";
  if (keys.length === TIER_FEATURES.length) return "Everything";
  return keys.map((key) => TIER_FEATURES.find((feature) => feature.key === key)?.label ?? key).join(", ");
}
