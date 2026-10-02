import { z } from "zod";

import { GranularitySchema } from "@/features/costs/schemas";

const WindowFields = {
  period: z.string().nullable(),
  fromDate: z.string(),
  toDate: z.string(),
  granularity: GranularitySchema,
};

export const ValueTotalsSchema = z.object({
  successfulWrites: z.number().int(),
  minutesSaved: z.number().int(),
  value: z.number().nullable(),
  spend: z.number(),
  valueToSpendRatio: z.number().nullable(),
  unverifiedWrites: z.number().int(),
  failedWrites: z.number().int(),
  unclassifiedActions: z.number().int(),
  hourlyRateUsd: z.number().nullable(),
});

export const ValueSeriesPointSchema = z.object({
  bucket: z.string(),
  minutesSaved: z.number().int(),
  value: z.number().nullable(),
  spend: z.number(),
});

export const AgentValueSchema = z.object({
  agentId: z.string().uuid().nullable(),
  agentName: z.string().nullable(),
  agentDeleted: z.boolean(),
  successfulWrites: z.number().int(),
  minutesSaved: z.number().int(),
  value: z.number().nullable(),
  spend: z.number(),
  valueToSpendRatio: z.number().nullable(),
});

export const OutcomeTypeValueSchema = z.object({
  outcomeType: z.string(),
  successfulWrites: z.number().int(),
  effectiveMinutes: z.number().int(),
  minutesSaved: z.number().int(),
  value: z.number().nullable(),
});

export const OrganizationValueSchema = z.object({
  ...WindowFields,
  totals: ValueTotalsSchema,
  series: z.array(ValueSeriesPointSchema),
  agents: z.array(AgentValueSchema),
  topOutcomeTypes: z.array(OutcomeTypeValueSchema),
});

export const ActivityTotalsSchema = z.object({
  requests: z.number().int(),
  handledWithoutFailureRate: z.number().nullable(),
  handledCoverage: z.number().int(),
  medianResponseSeconds: z.number().nullable(),
  responseTimeCoverage: z.number().int(),
  costPerRequest: z.number().nullable(),
  toolCallsPerRequest: z.number().nullable(),
});

export const ActivitySeriesPointSchema = z.object({
  bucket: z.string(),
  requests: z.number().int(),
});

export const AgentActivitySchema = ActivityTotalsSchema.extend({
  agentId: z.string().uuid().nullable(),
  agentName: z.string().nullable(),
  agentDeleted: z.boolean(),
  spend: z.number(),
});

export const OrganizationActivitySchema = z.object({
  ...WindowFields,
  totals: ActivityTotalsSchema,
  requestsSeries: z.array(ActivitySeriesPointSchema),
  agents: z.array(AgentActivitySchema),
});

export type ValueTotals = z.infer<typeof ValueTotalsSchema>;
export type ValueSeriesPoint = z.infer<typeof ValueSeriesPointSchema>;
export type AgentValue = z.infer<typeof AgentValueSchema>;
export type OutcomeTypeValue = z.infer<typeof OutcomeTypeValueSchema>;
export type OrganizationValue = z.infer<typeof OrganizationValueSchema>;
export type ActivityTotals = z.infer<typeof ActivityTotalsSchema>;
export type ActivitySeriesPoint = z.infer<typeof ActivitySeriesPointSchema>;
export type AgentActivity = z.infer<typeof AgentActivitySchema>;
export type OrganizationActivity = z.infer<typeof OrganizationActivitySchema>;
