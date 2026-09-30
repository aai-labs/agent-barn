import { z } from "zod";

import { AgentPermissionKeySchema } from "@/features/agents/schemas";

export const ResourceUsageRangeSchema = z.enum(["1h", "6h", "24h", "7d", "14d"]);
export type ResourceUsageRange = z.infer<typeof ResourceUsageRangeSchema>;

/** Whether the numbers could be fetched at all. About the source, not the Agent. */
export const ResourceUsageAvailabilitySchema = z.enum([
  "available",
  "not_configured",
  "unavailable",
]);
export type ResourceUsageAvailability = z.infer<typeof ResourceUsageAvailabilitySchema>;

/** What the source knows about one Agent. */
export const ResourceUsageStateSchema = z.enum([
  "reporting",
  "restart_required",
  "unsupported",
  "no_data",
]);
export type ResourceUsageState = z.infer<typeof ResourceUsageStateSchema>;

export const ResourceUsagePointSchema = z.object({
  bucket: z.string(),
  memoryWorkingSetBytes: z.number().nullable().default(null),
  cpuCores: z.number().nullable().default(null),
  cpuThrottledRatio: z.number().nullable().default(null),
});
export type ResourceUsagePoint = z.infer<typeof ResourceUsagePointSchema>;

export const AgentResourceUsageSchema = z.object({
  agentId: z.string().uuid(),
  range: ResourceUsageRangeSchema,
  fromDate: z.string(),
  toDate: z.string(),
  stepSeconds: z.number().int(),
  availability: ResourceUsageAvailabilitySchema,
  /** Null unless the source was reachable. */
  state: ResourceUsageStateSchema.nullable().default(null),
  observedAt: z.string(),
  memoryWorkingSetBytes: z.number().nullable().default(null),
  memoryLimitBytes: z.number().nullable().default(null),
  memoryPeakBytes: z.number().nullable().default(null),
  cpuCores: z.number().nullable().default(null),
  cpuLimitCores: z.number().nullable().default(null),
  cpuAverageCores: z.number().nullable().default(null),
  /** Share (0 to 1) of scheduling periods in which the container hit its CPU limit. */
  cpuThrottledRatio: z.number().nullable().default(null),
  /** One entry per step; a missing reading is null so a gap shows as a gap. */
  series: z.array(ResourceUsagePointSchema).default([]),
});
export type AgentResourceUsage = z.infer<typeof AgentResourceUsageSchema>;

export const AgentUsageSnapshotSchema = z.object({
  state: ResourceUsageStateSchema,
  memoryWorkingSetBytes: z.number().nullable().default(null),
  memoryLimitBytes: z.number().nullable().default(null),
  cpuCores: z.number().nullable().default(null),
  cpuLimitCores: z.number().nullable().default(null),
  cpuThrottledRatio: z.number().nullable().default(null),
});
export type AgentUsageSnapshot = z.infer<typeof AgentUsageSnapshotSchema>;

export const AgentOverviewSpendSchema = z.object({
  spend: z.number(),
  calls: z.number().int(),
  lastCallAt: z.string().nullable().default(null),
});
export type AgentOverviewSpend = z.infer<typeof AgentOverviewSpendSchema>;

export const AgentOverviewItemSchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  status: z.enum(["STOPPED", "RUNNING", "ERROR"]),
  agentType: z.enum(["openclaw", "hermes"]).default("openclaw"),
  effectiveModel: z.string().default(""),
  createdAt: z.string(),
  allowedActions: z.array(AgentPermissionKeySchema).default([]),
  /** Null without `cost.read` on this Agent. An Agent with no calls has zero spend. */
  spend: AgentOverviewSpendSchema.nullable().default(null),
  /** Null without `activity.read`, and for a stopped Agent (no container to measure). */
  resourceUsage: AgentUsageSnapshotSchema.nullable().default(null),
});
export type AgentOverviewItem = z.infer<typeof AgentOverviewItemSchema>;

export const AgentOverviewSchema = z.object({
  period: z.string().nullable().default(null),
  fromDate: z.string(),
  toDate: z.string(),
  resourceUsageAvailability: ResourceUsageAvailabilitySchema,
  /** Every Agent the caller can read; `items` stops at a cap. */
  total: z.number().int(),
  items: z.array(AgentOverviewItemSchema),
});
export type AgentOverview = z.infer<typeof AgentOverviewSchema>;
