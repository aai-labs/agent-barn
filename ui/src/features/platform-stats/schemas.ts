import { z } from "zod";

// Platform Oversight projections (AF-256): counts only. The API deliberately
// carries no message content, sender/channel/session identity, or any other
// tenant data, so there is nothing here to widen.

export const StatsPeriodSchema = z.enum([
  "SEVEN_DAYS",
  "THIRTY_DAYS",
  "NINETY_DAYS",
]);

export const GranularitySchema = z.enum(["minute", "hour", "day", "week"]);

export const PlatformMessageSeriesPointSchema = z.object({
  bucket: z.string(),
  inbound: z.number(),
  outbound: z.number(),
});

export const PlatformMessageStatsSchema = z.object({
  observedAt: z.string(),
  period: StatsPeriodSchema.nullable(),
  fromDate: z.string(),
  toDate: z.string(),
  granularity: GranularitySchema,
  inbound: z.number(),
  outbound: z.number(),
  total: z.number(),
  series: z.array(PlatformMessageSeriesPointSchema),
});

export const PlatformAgentSeriesPointSchema = z.object({
  bucket: z.string(),
  existing: z.number(),
  created: z.number(),
  // Agents with observable telemetry that day — a message or a tool call.
  // Always a lower bound on how many were up.
  active: z.number(),
});

export const PlatformAgentStatsSchema = z.object({
  observedAt: z.string(),
  period: StatsPeriodSchema.nullable(),
  fromDate: z.string(),
  toDate: z.string(),
  granularity: GranularitySchema,
  total: z.number(),
  running: z.number(),
  stopped: z.number(),
  errored: z.number(),
  active: z.number(),
  series: z.array(PlatformAgentSeriesPointSchema),
});

export const AgentPlatformSchema = z.enum(["slack", "teams", "telegram", "discord"]);

export const MessageDirectionSchema = z.enum(["all", "inbound", "outbound"]);

// Narrowing dimensions the oversight boundary allows. There is deliberately no
// "who sent the message" filter: sender identity is excluded from these
// projections, so the API cannot answer it.
export type StatsFilters = {
  organizationId?: string;
  platform?: AgentPlatform;
};

// Both bounds are optional so a lone `from` runs to now and a lone `to` backs
// off by the default period's length.
export type StatsRange = {
  fromDate?: string;
  toDate?: string;
};

export type AgentPlatform = z.infer<typeof AgentPlatformSchema>;
export type MessageDirection = z.infer<typeof MessageDirectionSchema>;
export type PlatformAgentSeriesPoint = z.infer<
  typeof PlatformAgentSeriesPointSchema
>;
export type Granularity = z.infer<typeof GranularitySchema>;
export type StatsPeriod = z.infer<typeof StatsPeriodSchema>;
export type PlatformMessageSeriesPoint = z.infer<
  typeof PlatformMessageSeriesPointSchema
>;
export type PlatformMessageStats = z.infer<typeof PlatformMessageStatsSchema>;
export type PlatformAgentStats = z.infer<typeof PlatformAgentStatsSchema>;
