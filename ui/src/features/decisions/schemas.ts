import { z } from "zod";

export const PlatformDecisionSettingsSchema = z.object({
  model: z.string(),
  updatedAt: z.string().nullable().optional(),
});
export const PlatformDecisionModelsSchema = z.array(z.object({ value: z.string(), label: z.string() }));

export type PlatformDecisionSettings = z.infer<typeof PlatformDecisionSettingsSchema>;
export type PlatformDecisionModels = z.infer<typeof PlatformDecisionModelsSchema>;
