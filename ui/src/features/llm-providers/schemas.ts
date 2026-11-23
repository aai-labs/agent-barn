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

export const LlmProviderModelSchema = z.object({
  modelId: z.string(),
  inputCostPerToken: z.string(),
  outputCostPerToken: z.string(),
  cacheReadInputTokenCost: z.string(),
  cacheCreationInputTokenCost: z.string(),
  priceSource: z.enum(["litellm", "manual"]),
  litellmPriceKey: z.string().nullable(),
});

export type LlmProviderModel = z.infer<typeof LlmProviderModelSchema>;

export const LlmProviderModelListSchema = z.array(LlmProviderModelSchema);

export const LlmProviderCatalogueEntrySchema = z.object({
  modelId: z.string(),
  stored: z.boolean(),
  litellmPriceKey: z.string().nullable(),
  inputCostPerToken: z.string().nullable(),
  outputCostPerToken: z.string().nullable(),
  cacheReadInputTokenCost: z.string().nullable(),
  cacheCreationInputTokenCost: z.string().nullable(),
  pricesDiffer: z.boolean(),
});

export type LlmProviderCatalogueEntry = z.infer<typeof LlmProviderCatalogueEntrySchema>;

export const LlmProviderCatalogueSchema = z.array(LlmProviderCatalogueEntrySchema);

export type ModelChoice = {
  modelId: string;
  price: "litellm" | "stored";
};
