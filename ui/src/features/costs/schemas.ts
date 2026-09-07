import { z } from "zod";

export const CostSortDirectionSchema = z.enum([
  "newest_first",
  "oldest_first",
  "most_expensive",
]);

export const GranularitySchema = z.enum(["minute", "hour", "day", "week"]);

/** One billed LLM call. `healed` marks a cost recovered from OpenRouter rather
 *  than reported by the proxy — it is why a historical total can go up. */
export const CostRecordSchema = z.object({
  requestId: z.string(),
  occurredAt: z.string(),
  spend: z.number(),
  promptTokens: z.number().int(),
  completionTokens: z.number().int(),
  totalTokens: z.number().int(),
  model: z.string(),
  status: z.string(),
  requestDurationMs: z.number().int().nullable().default(null),
  agentId: z.string().uuid().nullable().default(null),
  agentName: z.string().nullable().default(null),
  healed: z.boolean().default(false),
});

export const PlatformCostRecordSchema = CostRecordSchema.extend({
  organizationId: z.string().uuid().nullable().default(null),
  organizationName: z.string().nullable().default(null),
});

export const PaginatedCostRecordsSchema = z.object({
  page: z.number().int().min(1),
  pageSize: z.number().int().min(1),
  total: z.number().int().min(0),
  items: z.array(CostRecordSchema),
});

export const PaginatedPlatformCostRecordsSchema = z.object({
  page: z.number().int().min(1),
  pageSize: z.number().int().min(1),
  total: z.number().int().min(0),
  items: z.array(PlatformCostRecordSchema),
});

export const CostSeriesPointSchema = z.object({
  bucket: z.string(),
  spend: z.number(),
  calls: z.number().int(),
});

export const AgentSpendSeriesPointSchema = z.object({
  bucket: z.string(),
  agentId: z.string().uuid().nullable().default(null),
  agentName: z.string().nullable().default(null),
  spend: z.number(),
});

export const TokenSeriesPointSchema = z.object({
  bucket: z.string(),
  avgPromptTokens: z.number(),
});

/** `upper` is null on the final open-ended band: a handful of very expensive
 *  calls is exactly what the distribution exists to show. */
export const CostHistogramBucketSchema = z.object({
  lower: z.number(),
  upper: z.number().nullable(),
  calls: z.number().int(),
});

export const CostFilterOptionSchema = z.object({
  value: z.string(),
  label: z.string(),
});

export const CostSummarySchema = z.object({
  period: z.string().nullable().default(null),
  fromDate: z.string(),
  toDate: z.string(),
  granularity: GranularitySchema,
  totalSpend: z.number(),
  totalCalls: z.number().int(),
  activeAgents: z.number().int(),
  topModel: z.string().nullable().default(null),
  topModelSpend: z.number().default(0),
  avgCostPerCall: z.number().default(0),
  avgPromptTokens: z.number().default(0),
  spendOverTime: z.array(CostSeriesPointSchema).default([]),
  avgPromptTokensOverTime: z.array(TokenSeriesPointSchema).default([]),
  spendByAgentOverTime: z.array(AgentSpendSeriesPointSchema).default([]),
  costPerCallHistogram: z.array(CostHistogramBucketSchema).default([]),
});

export const OrganizationSpendSchema = z.object({
  organizationId: z.string().uuid().nullable().default(null),
  organizationName: z.string().nullable().default(null),
  spend: z.number(),
  calls: z.number().int(),
  agents: z.number().int(),
});

export const PlatformCostSummarySchema = CostSummarySchema.extend({
  dailyBurnRate: z.number().default(0),
  creditsRemaining: z.number().nullable().default(null),
  runwayDays: z.number().nullable().default(null),
  unattributedSpend: z.number().default(0),
  unattributedCalls: z.number().int().default(0),
  organizations: z.array(OrganizationSpendSchema).default([]),
});

/** Cost totals for a single agent, used by the agent detail surface. */
export const AgentModelBreakdownSchema = z.object({
  model: z.string(),
  totalCost: z.number(),
  promptTokens: z.number().int(),
  completionTokens: z.number().int(),
});

export const AgentCostSchema = z.object({
  agentId: z.string().uuid(),
  agentName: z.string(),
  model: z.string(),
  status: z.string(),
  totalCost: z.number(),
  totalTokens: z.number().int(),
  promptTokens: z.number().int(),
  completionTokens: z.number().int(),
  modelsBreakdown: z.array(AgentModelBreakdownSchema).default([]),
});

export type CostSortDirection = z.infer<typeof CostSortDirectionSchema>;
export type Granularity = z.infer<typeof GranularitySchema>;
export type CostRecord = z.infer<typeof CostRecordSchema>;
export type PlatformCostRecord = z.infer<typeof PlatformCostRecordSchema>;
export type PaginatedCostRecords = z.infer<typeof PaginatedCostRecordsSchema>;
export type PaginatedPlatformCostRecords = z.infer<
  typeof PaginatedPlatformCostRecordsSchema
>;
export type CostSeriesPoint = z.infer<typeof CostSeriesPointSchema>;
export type AgentSpendSeriesPoint = z.infer<typeof AgentSpendSeriesPointSchema>;
export type TokenSeriesPoint = z.infer<typeof TokenSeriesPointSchema>;
export type CostHistogramBucket = z.infer<typeof CostHistogramBucketSchema>;
export type CostFilterOption = z.infer<typeof CostFilterOptionSchema>;
export type CostSummary = z.infer<typeof CostSummarySchema>;
export type OrganizationSpend = z.infer<typeof OrganizationSpendSchema>;
export type PlatformCostSummary = z.infer<typeof PlatformCostSummarySchema>;
export type AgentCost = z.infer<typeof AgentCostSchema>;
