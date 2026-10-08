import { z } from "zod";

export const WebhookDeliveryPlatformSchema = z.enum([
  "slack",
  "discord",
  "telegram",
  "teams",
]);

export const WebhookDeliveryPlatformReadSchema = z.object({
  key: WebhookDeliveryPlatformSchema,
  displayName: z.string(),
});

export const AgentWebhookSchema = z.object({
  id: z.string().uuid(),
  agentId: z.string().uuid(),
  displayName: z.string(),
  deliveryPlatform: WebhookDeliveryPlatformSchema,
  enabled: z.boolean(),
  revision: z.number().int().positive(),
  webhookUrl: z.string().url().nullable(),
  signingSecret: z.string().nullable().optional(),
  createdAt: z.string(),
  updatedAt: z.string(),
});

export const WebhookInvocationSchema = z.object({
  id: z.string().uuid(),
  webhookId: z.string().uuid(),
  externalEventId: z.string().nullable(),
  prompt: z.string(),
  status: z.enum(["RECEIVED", "SUBMITTED", "DISPATCH_FAILED"]),
  dispatchAttemptCount: z.number().int().nonnegative(),
  dispatchGeneration: z.number().int().positive(),
  submittedAt: z.string().nullable(),
  nativeJobId: z.string().nullable(),
  lastErrorCode: z.string().nullable(),
  lastErrorMessage: z.string().nullable(),
  createdAt: z.string(),
  updatedAt: z.string(),
});

export const PaginatedWebhookInvocationsSchema = z.object({
  page: z.number().int().positive(),
  pageSize: z.number().int().positive(),
  total: z.number().int().nonnegative(),
  items: z.array(WebhookInvocationSchema),
});

export type AgentWebhook = z.infer<typeof AgentWebhookSchema>;
export type WebhookDeliveryPlatform = z.infer<
  typeof WebhookDeliveryPlatformSchema
>;
export type WebhookDeliveryPlatformRead = z.infer<
  typeof WebhookDeliveryPlatformReadSchema
>;
export type WebhookInvocation = z.infer<typeof WebhookInvocationSchema>;
export type PaginatedWebhookInvocations = z.infer<
  typeof PaginatedWebhookInvocationsSchema
>;
