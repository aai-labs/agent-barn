import { z } from "zod";

export const ProviderTypeSchema = z.enum([
  "openrouter",
  "anthropic",
  "openai",
  "gemini",
  "xai",
  "deepseek",
  "fireworks",
  "novita",
  "azure",
  "custom",
]);

export type ProviderType = z.infer<typeof ProviderTypeSchema>;

export const LlmProviderConnectionSchema = z.object({
  slug: z.string(),
  name: z.string(),
  providerType: ProviderTypeSchema,
  baseUrl: z.string().nullable(),
  hasApiKey: z.boolean(),
  apiKeyLast4: z.string().nullable(),
  updatedAt: z.string().nullable(),
  updatedBy: z.string().nullable(),
  envKeyConfigured: z.boolean(),
});

export type LlmProviderConnection = z.infer<typeof LlmProviderConnectionSchema>;

export const LlmProviderConnectionListSchema = z.array(LlmProviderConnectionSchema);

export type NewLlmProviderConnection = {
  providerType: ProviderType;
  apiKey: string;
  slug?: string;
  name?: string;
  baseUrl?: string;
};

export type KeyReplacement = {
  apiKey: string;
  baseUrl?: string;
};
