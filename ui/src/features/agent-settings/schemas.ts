import { z } from "zod";

export const AgentSettingsSchema = z.object({
  // The organization's own choice. Null means it follows the platform default.
  defaultModel: z.string().nullable(),
  // What the default resolves to right now, so the UI can name the model an
  // inheriting Agent will run without asking a second endpoint.
  effectiveDefaultModel: z.string(),
  defaultModelSource: z.enum(["organization", "platform"]),
  inheritingAgentCount: z.number(),
  overrideAgentCount: z.number(),
  // The organization's own default Agent spend limit. Null follows the platform's.
  defaultAgentLlmBudgetUsd: z.number().nullable(),
  // What an Agent without a limit of its own is held to right now.
  effectiveDefaultAgentLlmBudgetUsd: z.number(),
  budgetInheritingAgentCount: z.number(),
  budgetOverrideAgentCount: z.number(),
  canManageLlmBudget: z.boolean(),
  updatedAt: z.string().nullable(),
});

export type AgentSettings = z.infer<typeof AgentSettingsSchema>;

// Each field is optional: an omitted setting is left untouched, null reverts it to
// the platform's.
export const AgentSettingsUpdateSchema = z.object({
  defaultModel: z.string().nullable().optional(),
  defaultAgentLlmBudgetUsd: z.number().nullable().optional(),
});

export type AgentSettingsUpdate = z.infer<typeof AgentSettingsUpdateSchema>;
