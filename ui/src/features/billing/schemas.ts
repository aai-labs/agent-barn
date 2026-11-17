import { z } from "zod";

import { OrganizationTierSchema } from "@/features/tiers/schemas";

/** A subscription that keeps an organization on a paid tier. */
export const SubscriptionSchema = z.object({
  id: z.string().uuid(),
  tier: OrganizationTierSchema,
  status: z.enum(["active", "past_due", "canceled"]),
  provider: z.enum(["mock", "stripe"]),
  currentPeriodStart: z.string(),
  currentPeriodEnd: z.string(),
  cancelAtPeriodEnd: z.boolean(),
  // The smaller tier it moves to when this period ends, if one was chosen.
  scheduledTier: OrganizationTierSchema.nullable().optional(),
  // When a renewal payment failed, and when the tier is lost unless it's paid by then.
  pastDueSince: z.string().nullable().optional(),
  graceEndsAt: z.string().nullable().optional(),
  // Whether the payment provider has a page for the card, billing details and invoices.
  manageable: z.boolean().default(false),
  // This period's usage, and what's left of it as of the last spend snapshot.
  allowanceUsd: z.number(),
  allowanceRemainingUsd: z.number(),
});

/** Where the owner manages the card, billing details and invoices. */
export const SubscriptionPortalSchema = z.object({ url: z.string().url() });

export const CreditKindSchema = z.enum([
  "trial",
  "purchase",
  "refund",
  "chargeback",
  "adjustment",
  "tier_credit",
  "allowance",
  "allowance_expiry",
]);

export const CreditHistoryItemSchema = z.object({
  kind: CreditKindSchema,
  creditUsd: z.number(),
  amountPaidUsd: z.number().nullable().optional(),
  // Who bought it, for a purchase.
  purchasedBy: z.string().nullable().optional(),
  createdAt: z.string(),
});

export const OrganizationBillingSchema = z.object({
  // Whether this organization can buy credit right now.
  available: z.boolean(),
  // Whether it runs on credit at all, rather than on a limit its plan renews.
  onCredit: z.boolean(),
  creditUsd: z.number(),
  // Null until spend has been observed.
  spendUsd: z.number().nullable().optional(),
  balanceUsd: z.number().nullable().optional(),
  minPurchaseUsd: z.number(),
  maxPurchaseUsd: z.number(),
  purchaseFeePercent: z.number(),
  // Free and none subscribe to a paid tier before they can buy credit.
  upgradeRequired: z.boolean().default(false),
  tier: OrganizationTierSchema.nullable().optional(),
  // Whether it may subscribe to a paid tier here.
  subscriptionsAvailable: z.boolean().default(false),
  // Who takes a new subscription's payment: Stripe, or "mock" for demo payments.
  subscriptionProvider: z.enum(["mock", "stripe"]).nullable().optional(),
  tierAssignedByPlatform: z.boolean().default(false),
  subscription: SubscriptionSchema.nullable().optional(),
  // Newest first.
  history: z.array(CreditHistoryItemSchema),
});

export const SubscriptionStartSchema = z.object({
  outcome: z.enum(["active", "redirect"]),
  redirectUrl: z.string().nullable().optional(),
  subscription: SubscriptionSchema.nullable().optional(),
});

export const CheckoutSchema = z.object({ url: z.string() });

export const PlatformCreditRecordSchema = z.object({
  organizationId: z.string(),
  organizationName: z.string(),
  kind: CreditKindSchema,
  creditUsd: z.number(),
  amountPaidUsd: z.number().nullable().optional(),
  // The buyer, a Platform Administrator, or the payment provider.
  by: z.string(),
  // The payment provider's reference, when there is one.
  reference: z.string().nullable().optional(),
  createdAt: z.string(),
});

export const PaginatedPlatformCreditRecordsSchema = z.object({
  page: z.number().int().min(1),
  pageSize: z.number().int().min(1),
  total: z.number().int().min(0),
  items: z.array(PlatformCreditRecordSchema),
});

export const BillingSettingsSchema = z.object({
  // Turned on by a Platform Administrator.
  paymentsEnabled: z.boolean(),
  // Whether this deployment has what payments need; without it they can't be turned on.
  paymentsConfigured: z.boolean(),
  minPurchaseUsd: z.number(),
  maxPurchaseUsd: z.number(),
  purchaseFeePercent: z.number(),
  // How long a subscription whose payment failed keeps its tier.
  paymentGraceDays: z.number().int(),
  updatedAt: z.string().nullable().optional(),
});

export type CreditHistoryItem = z.infer<typeof CreditHistoryItemSchema>;
export type Subscription = z.infer<typeof SubscriptionSchema>;
export type OrganizationBilling = z.infer<typeof OrganizationBillingSchema>;
export type BillingSettings = z.infer<typeof BillingSettingsSchema>;
export type CreditKind = z.infer<typeof CreditKindSchema>;
export type PlatformCreditRecord = z.infer<typeof PlatformCreditRecordSchema>;
export type PaginatedPlatformCreditRecords = z.infer<typeof PaginatedPlatformCreditRecordsSchema>;
