import { z } from "zod";

export const CreditKindSchema = z.enum(["trial", "purchase", "refund", "chargeback", "adjustment"]);

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
  creditRate: z.number(),
  purchaseFeePercent: z.number(),
  // Newest first.
  history: z.array(CreditHistoryItemSchema),
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
  creditRate: z.number(),
  purchaseFeePercent: z.number(),
  updatedAt: z.string().nullable().optional(),
});

export type CreditHistoryItem = z.infer<typeof CreditHistoryItemSchema>;
export type OrganizationBilling = z.infer<typeof OrganizationBillingSchema>;
export type BillingSettings = z.infer<typeof BillingSettingsSchema>;
export type CreditKind = z.infer<typeof CreditKindSchema>;
export type PlatformCreditRecord = z.infer<typeof PlatformCreditRecordSchema>;
export type PaginatedPlatformCreditRecords = z.infer<typeof PaginatedPlatformCreditRecordsSchema>;
