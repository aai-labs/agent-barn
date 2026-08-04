import { z } from "zod";

export const EventDeliveryStatusSchema = z.enum([
  "PENDING",
  "ENQUEUED",
  "PROCESSING",
  "SUCCEEDED",
  "DEAD_LETTERED",
]);

export const EventDeliveryDeadLetterReasonSchema = z.enum([
  "RETRY_EXHAUSTED",
  "TERMINAL_HANDLER_ERROR",
  "UNKNOWN_HANDLER",
  "UNSUPPORTED_EVENT",
  "INVALID_DELIVERY",
]);

export const EventDeliverySortDirectionSchema = z.enum([
  "NEWEST_FIRST",
  "OLDEST_FIRST",
]);

export const EventDeliverySchema = z.object({
  id: z.string().uuid(),
  eventId: z.string().uuid(),
  eventName: z.string(),
  schemaVersion: z.number().int(),
  handlerName: z.string(),
  organizationId: z.string().uuid(),
  organizationName: z.string(),
  status: EventDeliveryStatusSchema,
  attemptCount: z.number().int(),
  deadLetterReason: EventDeliveryDeadLetterReasonSchema.nullable(),
  lastError: z.string().nullable(),
  createdAt: z.string(),
  enqueuedAt: z.string().nullable(),
  claimedAt: z.string().nullable(),
  completedAt: z.string().nullable(),
  statusSince: z.string().nullable(),
  observedAt: z.string(),
});

export const PaginatedEventDeliveriesSchema = z.object({
  page: z.number().int().min(1),
  pageSize: z.number().int().min(1),
  total: z.number().int().min(0),
  items: z.array(EventDeliverySchema),
});

export const EventDeliveryActiveStateStatsSchema = z.object({
  count: z.number().int(),
  oldestAgeSeconds: z.number().nullable(),
  staleThresholdSeconds: z.number().int(),
  staleCount: z.number().int(),
  unknownAgeCount: z.number().int(),
});

export const EventDeliverySummarySchema = z.object({
  observedAt: z.string(),
  totalCount: z.number().int(),
  statusCounts: z.object({
    pending: z.number().int(),
    enqueued: z.number().int(),
    processing: z.number().int(),
    succeeded: z.number().int(),
    deadLettered: z.number().int(),
  }),
  pending: EventDeliveryActiveStateStatsSchema,
  enqueued: EventDeliveryActiveStateStatsSchema,
  processing: EventDeliveryActiveStateStatsSchema,
});

export const SupportedEventTypeSchema = z.object({
  eventName: z.string(),
  schemaVersions: z.array(z.number().int()),
});

export const SupportedEventTypesSchema = z.array(SupportedEventTypeSchema);

export type EventDeliveryStatus = z.infer<typeof EventDeliveryStatusSchema>;
export type EventDeliverySortDirection = z.infer<
  typeof EventDeliverySortDirectionSchema
>;
export type EventDelivery = z.infer<typeof EventDeliverySchema>;
export type PaginatedEventDeliveries = z.infer<
  typeof PaginatedEventDeliveriesSchema
>;
export type EventDeliveryActiveStateStats = z.infer<
  typeof EventDeliveryActiveStateStatsSchema
>;
export type EventDeliverySummary = z.infer<typeof EventDeliverySummarySchema>;
export type SupportedEventType = z.infer<typeof SupportedEventTypeSchema>;
