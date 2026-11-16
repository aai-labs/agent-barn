import { z } from "zod";

export const SensitivitySchema = z.enum(["LOW", "NORMAL", "HIGH"]);
export type Sensitivity = z.infer<typeof SensitivitySchema>;

export const RateSignalSchema = z.enum([
  "LLM_TOKENS_PER_HOUR",
  "LLM_CALLS_PER_HOUR",
  "TOOL_CALLS_PER_HOUR",
  "TOOL_ERROR_RATE",
  "WRITES_PER_HOUR",
]);
export type RateSignal = z.infer<typeof RateSignalSchema>;

export const AnomalySignalSchema = z.enum([
  ...RateSignalSchema.options,
  "LLM_TOKENS_CAP",
  "LLM_CALLS_CAP",
  "NEW_TOOL",
  "NEW_INTEGRATION",
  "NEW_INTEGRATION_ACTION",
  "NEW_DESTINATION",
]);
export type AnomalySignal = z.infer<typeof AnomalySignalSchema>;

export const AnomalyDetectionSettingsSchema = z.object({
  enabled: z.boolean(),
  canManage: z.boolean(),
  updatedAt: z.string().nullable(),
});
export type AnomalyDetectionSettings = z.infer<typeof AnomalyDetectionSettingsSchema>;

export const AnomalySchema = z.object({
  id: z.string(),
  signal: AnomalySignalSchema,
  // The tool, integration, action or host a first use names; null for rates.
  subject: z.string().nullable(),
  observedValue: z.number(),
  usualValue: z.number().nullable(),
  threshold: z.number().nullable(),
  startedAt: z.string(),
  lastObservedAt: z.string(),
  // Null while the deviation is still going on.
  endedAt: z.string().nullable(),
  classificationState: z.enum(["STATISTICS_ONLY", "CLASSIFIED"]),
});
export type Anomaly = z.infer<typeof AnomalySchema>;

export const AnomalyPageSchema = z.object({
  page: z.number(),
  pageSize: z.number(),
  total: z.number(),
  items: z.array(AnomalySchema),
});
export type AnomalyPage = z.infer<typeof AnomalyPageSchema>;

export const AnomalyOverrideSchema = z.object({
  sensitivity: SensitivitySchema,
  maxLlmTokensPerHour: z.number().nullable(),
  maxLlmCallsPerHour: z.number().nullable(),
});
export type AnomalyOverride = z.infer<typeof AnomalyOverrideSchema>;

export const NormalBehaviourSchema = z.object({
  detectionEnabled: z.boolean(),
  enoughHistory: z.boolean(),
  activeDays: z.number(),
  rates: z.array(
    z.object({
      signal: RateSignalSchema,
      usual: z.number(),
      threshold: z.number(),
      activeHours: z.number(),
    }),
  ),
  tools: z.array(z.string()),
  integrations: z.array(z.string()),
  integrationActions: z.array(z.string()),
  destinations: z.array(z.string()),
  override: AnomalyOverrideSchema,
  canManage: z.boolean(),
});
export type NormalBehaviour = z.infer<typeof NormalBehaviourSchema>;
