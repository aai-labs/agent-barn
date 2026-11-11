import { z } from "zod";

export const TierActivationSchema = z.enum(["free", "paid", "contact", "none"]);
export type TierActivation = z.infer<typeof TierActivationSchema>;

/** One tier in the catalog. Amounts are US dollars as decimal strings, exactly as the API keeps them. */
export const TierSchema = z.object({
  id: z.string().uuid(),
  key: z.string(),
  name: z.string(),
  tagline: z.string().nullable(),
  activation: TierActivationSchema,
  /** Offered to new organizations. */
  enabled: z.boolean(),
  sortOrder: z.number().int(),
  priceUsd: z.string(),
  priceNote: z.string().nullable(),
  monthlyUsageUsd: z.string(),
  oneTimeCreditUsd: z.string(),
  agentLimit: z.number().int(),
  /** Null: every platform. */
  allowedPlatformKeys: z.array(z.string()).nullable(),
  features: z.array(z.string()),
  contactUrl: z.string().nullable(),
  /** Free and none: never deleted, and none never changes. */
  isSystem: z.boolean(),
  createdAt: z.string(),
  updatedAt: z.string(),
});
export type Tier = z.infer<typeof TierSchema>;

export const TierListSchema = z.array(TierSchema);

/** What the dialog edits. */
export type TierValues = {
  name: string;
  tagline: string | null;
  priceUsd: string;
  priceNote: string | null;
  monthlyUsageUsd: string;
  oneTimeCreditUsd: string;
  agentLimit: number;
  allowedPlatformKeys: string[] | null;
  features: string[];
  contactUrl: string | null;
};

export type TierCreate = TierValues & { key: string; activation: "paid" | "contact"; enabled?: boolean };

/** A partial edit; the key and activation never change. */
export type TierUpdate = Partial<TierValues & { enabled: boolean; sortOrder: number }>;

/** The tier an organization is on, as its members see it. */
export const OrganizationTierSchema = z.object({
  id: z.string().uuid(),
  key: z.string(),
  name: z.string(),
  activation: TierActivationSchema,
});
export type OrganizationTier = z.infer<typeof OrganizationTierSchema>;

/** What an organization's tier lets it use. Without a tier, everything. */
export const TierEntitlementsSchema = z.object({
  features: z.array(z.string()),
  /** Null: every platform. */
  allowedPlatformKeys: z.array(z.string()).nullable(),
});
export type TierEntitlements = z.infer<typeof TierEntitlementsSchema>;

/** One of the organization's live agents, with its tier hold if it is on one. */
export const TierHeldAgentSchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  status: z.string(),
  suspendedAt: z.string().nullable(),
});

/** A connection, agent webhook or agent memory on a tier hold. */
export const TierHeldItemSchema = z.object({
  id: z.string().uuid(),
  agentId: z.string().uuid(),
  agentName: z.string(),
  name: z.string(),
  platformKey: z.string().nullable().optional(),
  revision: z.number().int().nullable().optional(),
  suspendedAt: z.string().nullable(),
});
export type TierHeldItem = z.infer<typeof TierHeldItemSchema>;

export const TierHoldsSchema = z.object({
  agents: z.array(TierHeldAgentSchema),
  connections: z.array(TierHeldItemSchema),
  webhooks: z.array(TierHeldItemSchema),
  memory: z.array(TierHeldItemSchema),
});
export type TierHolds = z.infer<typeof TierHoldsSchema>;

/** What moving to another tier would put on hold now: the agents beyond its limit and the
 *  connections, webhooks and memory it leaves out. */
export const TierHoldPreviewSchema = TierHoldsSchema.extend({ tier: z.string() });
export type TierHoldPreview = z.infer<typeof TierHoldPreviewSchema>;

/** An offered tier as anyone sees it on the pricing page and in onboarding. */
export const PublicTierSchema = z.object({
  key: z.string(),
  name: z.string(),
  tagline: z.string().nullable(),
  activation: TierActivationSchema,
  priceUsd: z.string(),
  priceNote: z.string().nullable(),
  monthlyUsageUsd: z.string(),
  oneTimeCreditUsd: z.string(),
  agentLimit: z.number().int(),
  allowedPlatformKeys: z.array(z.string()).nullable(),
  features: z.array(z.string()),
  contactUrl: z.string().nullable(),
});
export const PublicTierListSchema = z.array(PublicTierSchema);
export type PublicTier = z.infer<typeof PublicTierSchema>;
