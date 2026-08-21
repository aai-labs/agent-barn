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
  updatedAt: z.string().nullable(),
});

export type AgentSettings = z.infer<typeof AgentSettingsSchema>;

export const AgentSettingsUpdateSchema = z.object({
  defaultModel: z.string().nullable(),
});

export type AgentSettingsUpdate = z.infer<typeof AgentSettingsUpdateSchema>;
