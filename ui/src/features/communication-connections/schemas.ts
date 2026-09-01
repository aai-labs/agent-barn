import { z } from "zod";

const JsonSchemaSchema = z.record(z.string(), z.unknown());

const CommunicationErrorDetailsSchema = z.object({
  category: z.enum([
    "authentication",
    "authorization",
    "configuration",
    "network",
    "provider_rejected",
    "provider_unavailable",
    "rate_limited",
    "timeout",
    "unknown",
  ]),
  operation: z.string(),
  httpStatus: z.number().int().min(100).max(599).nullable(),
  providerCode: z.string().nullable(),
  retryable: z.boolean(),
  retryAfterSeconds: z.number().int().min(0).max(86400).nullable(),
  requestId: z.string().nullable(),
});

export const CommunicationDirectoryEntrySchema = z.object({
  id: z.string(),
  label: z.string(),
  detail: z.string().nullable().optional(),
});

export const CommunicationPlatformSchema = z.object({
  key: z.string(),
  displayName: z.string(),
  schemaVersion: z.number().int().positive(),
  capabilities: z.array(z.string()),
  settingsSchema: JsonSchemaSchema,
  credentialsSchema: JsonSchemaSchema,
  setupHint: z.string().nullable().optional(),
  setupManifest: z.record(z.string(), z.unknown()).nullable().optional(),
  postSetupHint: z.string().nullable().optional(),
});

export const CommunicationConnectionSchema = z.object({
  id: z.string().uuid(),
  agentId: z.string().uuid(),
  platformKey: z.string(),
  displayName: z.string(),
  enabled: z.boolean(),
  schemaVersion: z.number().int().positive(),
  settings: z.record(z.string(), z.unknown()),
  externalIdentity: z.string().nullable(),
  observedStatus: z.enum(["PENDING", "CONNECTING", "CONNECTED", "DEGRADED", "ERROR"]).nullable(),
  lastHealthAt: z.string().nullable(),
  lastErrorCode: z.string().nullable(),
  lastErrorMessage: z.string().nullable(),
  lastErrorDetails: CommunicationErrorDetailsSchema.nullable().optional(),
  webhookUrl: z.string().url().nullable(),
  revision: z.number().int().positive(),
  createdAt: z.string(),
  updatedAt: z.string(),
});

export const CommunicationJournalEntrySchema = z.object({
  id: z.string().uuid(),
  connectionId: z.string().uuid(),
  deliveryId: z.string().uuid().nullable(),
  occurredAt: z.string(),
  stage: z.string(),
  disposition: z.string().nullable(),
  attemptNumber: z.number().int().nonnegative(),
  durationMs: z.number().nullable(),
  errorCode: z.string().nullable(),
  errorSummary: z.string().nullable(),
  errorDetails: CommunicationErrorDetailsSchema.nullable().optional(),
  direction: z.enum(["INBOUND", "OUTBOUND"]).nullable().optional(),
  deliveryStatus: z.enum(["PENDING", "PROCESSING", "SUCCEEDED", "DEAD_LETTERED", "CANCELLED", "UNAVAILABLE"]).nullable().optional(),
  queueWaitMs: z.number().nonnegative().nullable().optional(),
  processingMs: z.number().nonnegative().nullable().optional(),
  nextRetryAt: z.string().nullable().optional(),
});

export const PaginatedCommunicationJournalEntriesSchema = z.object({
  page: z.number().int().min(1),
  pageSize: z.number().int().min(1),
  total: z.number().int().min(0),
  items: z.array(CommunicationJournalEntrySchema),
});

export const CommunicationDiagnosticsSchema = z.object({
  connection: CommunicationConnectionSchema,
  providerConnectivity: z.enum(["PENDING", "CONNECTING", "CONNECTED", "DEGRADED", "ERROR"]).nullable(),
  endToEndHealth: z.enum(["healthy", "degraded", "no_data", "unavailable"]),
  pipeline: z.object({
    providerObserved: z.number().int().nonnegative(),
    policyAdmitted: z.number().int().nonnegative(),
    queued: z.number().int().nonnegative(),
    agentClaimed: z.number().int().nonnegative(),
    modelCompleted: z.number().int().nonnegative(),
    replyQueued: z.number().int().nonnegative(),
    providerDelivered: z.number().int().nonnegative(),
    deadLettered: z.number().int().nonnegative(),
  }),
  deliveryCounts: z.object({
    total: z.number().int().nonnegative(),
    pending: z.number().int().nonnegative(),
    processing: z.number().int().nonnegative(),
    succeeded: z.number().int().nonnegative(),
    deadLettered: z.number().int().nonnegative(),
    cancelled: z.number().int().nonnegative(),
    unavailable: z.number().int().nonnegative(),
  }),
  queueDepth: z.number().int().nonnegative(),
  oldestQueuedAgeSeconds: z.number().nonnegative().nullable(),
  oldestPendingDeliveryAgeSeconds: z.number().nonnegative().nullable(),
  latency: z.object({
    sampleCount: z.number().int().nonnegative(),
    averageMs: z.number().nonnegative().nullable(),
    p50Ms: z.number().nonnegative().nullable(),
    latestMs: z.number().nonnegative().nullable(),
  }),
  lastSuccessfulConnectionAt: z.string().nullable(),
  currentErrorAgeSeconds: z.number().nonnegative().nullable(),
  consecutiveFailureCount: z.number().int().nonnegative(),
  deliverySuccessRate: z.number().min(0).max(1).nullable(),
  recentFailures: z.array(z.object({
    occurredAt: z.string(),
    stage: z.string(),
    deliveryId: z.string().uuid().nullable(),
    errorCode: z.string().nullable(),
    errorSummary: z.string().nullable(),
    errorDetails: CommunicationErrorDetailsSchema.nullable().optional(),
  })),
  latestTransitions: z.array(z.object({
    occurredAt: z.string(),
    stage: z.string(),
    deliveryId: z.string().uuid().nullable(),
    disposition: z.string().nullable(),
    attemptNumber: z.number().int().nonnegative(),
    durationMs: z.number().nullable(),
  })),
  connectionHistory: z.array(z.object({
    status: z.enum(["PENDING", "CONNECTING", "CONNECTED", "DEGRADED", "ERROR"]),
    startedAt: z.string(),
    endedAt: z.string().nullable(),
    nextStatus: z.enum(["PENDING", "CONNECTING", "CONNECTED", "DEGRADED", "ERROR"]).nullable(),
    durationMs: z.number().nonnegative(),
    reconnectCount: z.number().int().nonnegative(),
    errorCode: z.string().nullable(),
    errorSummary: z.string().nullable(),
  })),
  connectionIncidents: z.array(z.object({
    startedAt: z.string(),
    outcome: z.enum(["RECONNECTED", "FAILED", "IN_PROGRESS"]),
    connectTimeMs: z.number().nonnegative().nullable(),
    outageMs: z.number().nonnegative().nullable(),
    causeCode: z.string().nullable(),
    causeSummary: z.string().nullable(),
    reconnectCount: z.number().int().nonnegative(),
  })),
  reconnectCount: z.number().int().nonnegative(),
  medianConnectTimeMs: z.number().nonnegative().nullable(),
  longestOutageMs: z.number().nonnegative().nullable(),
  windowStart: z.string(),
  windowEnd: z.string(),
});

export const CommunicationReconnectSchema = z.object({
  connection: CommunicationConnectionSchema,
  requestedAt: z.string(),
});

export const CommunicationRetrySchema = z.object({
  deliveryId: z.string().uuid(),
  status: z.enum(["PENDING", "PROCESSING", "SUCCEEDED", "DEAD_LETTERED", "CANCELLED", "UNAVAILABLE"]),
  attemptCount: z.number().int().nonnegative(),
  requestedAt: z.string(),
});

export type CommunicationDirectoryEntry = z.infer<typeof CommunicationDirectoryEntrySchema>;
export type CommunicationPlatform = z.infer<typeof CommunicationPlatformSchema>;
export type CommunicationConnection = z.infer<typeof CommunicationConnectionSchema>;
export type CommunicationDiagnostics = z.infer<typeof CommunicationDiagnosticsSchema>;
export type CommunicationJournalEntry = z.infer<typeof CommunicationJournalEntrySchema>;
export type PaginatedCommunicationJournalEntries = z.infer<typeof PaginatedCommunicationJournalEntriesSchema>;
export type CommunicationJournalKind = "delivery" | "connection";
export type CommunicationJournalWindow = Pick<CommunicationJournalFilters, "since" | "until">;

export const DELIVERY_JOURNAL_STAGES = [
  "queued",
  "agent_claimed",
  "model_completed",
  "reply_queued",
  "provider_delivery_attempted",
  "provider_delivered",
  "retry_requested",
  "dead_lettered",
  "recovered",
] as const;

export const CONNECTION_JOURNAL_STAGES = [
  "provider_observed",
  "policy_admitted",
  "policy_rejected",
  "connection_connecting",
  "connection_connected",
  "connection_degraded",
  "connection_error",
  "reconnect_requested",
] as const;

export type CommunicationJournalFilters = {
  since?: string;
  until?: string;
  stage?: string;
  failedOnly?: boolean;
  retryableOnly?: boolean;
  direction?: "INBOUND" | "OUTBOUND";
  deliveryId?: string;
  order?: "asc" | "desc";
};
export type CommunicationReconnect = z.infer<typeof CommunicationReconnectSchema>;
export type CommunicationRetry = z.infer<typeof CommunicationRetrySchema>;

export type CreateCommunicationConnection = {
  agentId: string;
  platformKey: string;
  displayName: string;
  enabled: boolean;
  settings: Record<string, unknown>;
  credentials: Record<string, unknown>;
};

export type UpdateCommunicationConnection = {
  agentId: string;
  connectionId: string;
  revision: number;
  displayName?: string;
  enabled?: boolean;
  settings?: Record<string, unknown>;
  credentials?: Record<string, unknown>;
};
