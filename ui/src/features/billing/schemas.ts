import { z } from "zod";

export const CreditHistoryItemSchema = z.object({
  kind: z.enum(["trial", "purchase", "refund", "chargeback", "adjustment"]),
  creditUsd: z.number(),
  amountPaidUsd: z.number().nullable().optional(),
  createdAt: z.string(),
});

export const OrganizationBillingSchema = z.object({
  // Whether this organization can buy credit at all.
  available: z.boolean(),
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

export const BillingSettingsSchema = z.object({
  paymentsEnabled: z.boolean(),
  minPurchaseUsd: z.number(),
  maxPurchaseUsd: z.number(),
  creditRate: z.number(),
  purchaseFeePercent: z.number(),
  updatedAt: z.string().nullable().optional(),
});

export type CreditHistoryItem = z.infer<typeof CreditHistoryItemSchema>;
export type OrganizationBilling = z.infer<typeof OrganizationBillingSchema>;
export type BillingSettings = z.infer<typeof BillingSettingsSchema>;
