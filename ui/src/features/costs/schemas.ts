import { z } from "zod";

export const agentModelBreakdownSchema = z.object({
  model: z.string(),
  totalCost: z.number(),
  promptTokens: z.number().int(),
  completionTokens: z.number().int(),
});

export const agentCostSchema = z.object({
  agentId: z.string().uuid(),
  agentName: z.string(),
  model: z.string(),
  status: z.string(),
  totalCost: z.number(),
  totalTokens: z.number().int(),
  promptTokens: z.number().int(),
  completionTokens: z.number().int(),
  // This Agent's share of Honcho's spend. It is not on the Agent's own LiteLLM
  // key — Honcho bills one fleet-wide credential — so it is reported separately
  // rather than folded into totalCost, and is 0 when memory is off.
  memoryCost: z.number().default(0),
  modelsBreakdown: z.array(agentModelBreakdownSchema).default([]),
});

export const modelCostSchema = z.object({
  model: z.string(),
  totalCost: z.number(),
});

export const costSeriesPointSchema = z.object({
  date: z.string(),
  cost: z.number(),
});

export const costSummarySchema = z.object({
  totalCost: z.number(),
  // Memory spend for this Organization's Agents only, not the fleet total.
  totalMemoryCost: z.number().default(0),
  agents: z.array(agentCostSchema),
  byModel: z.array(modelCostSchema),
  timeSeries: z.array(costSeriesPointSchema),
});

export type AgentCost = z.infer<typeof agentCostSchema>;
export type ModelCost = z.infer<typeof modelCostSchema>;
export type CostSeriesPoint = z.infer<typeof costSeriesPointSchema>;
export type CostSummary = z.infer<typeof costSummarySchema>;
