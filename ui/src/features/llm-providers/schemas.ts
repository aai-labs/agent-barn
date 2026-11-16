import { z } from "zod";

export const OpenRouterConnectionSchema = z.object({
  hasApiKey: z.boolean(),
  apiKeyLast4: z.string().nullable(),
  updatedAt: z.string().nullable(),
  updatedBy: z.string().nullable(),
  envKeyConfigured: z.boolean(),
});

export type OpenRouterConnection = z.infer<typeof OpenRouterConnectionSchema>;
