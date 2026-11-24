import type { PriceField, ProviderType } from "./schemas";

export const PROVIDER_TYPE_LABELS: Record<ProviderType, string> = {
  openrouter: "OpenRouter",
  anthropic: "Anthropic",
  openai: "OpenAI",
  gemini: "Google",
  xai: "xAI",
  deepseek: "DeepSeek",
  fireworks: "Fireworks",
  novita: "Novita",
  azure: "Azure OpenAI",
  custom: "Custom endpoint",
};

export const PROVIDER_SUBTITLES: Record<ProviderType, string> = {
  openrouter: "Models from many providers",
  anthropic: "Claude models",
  openai: "GPT and o-series",
  gemini: "Gemini models",
  xai: "Grok models",
  deepseek: "DeepSeek models",
  fireworks: "Hosted open models",
  novita: "Hosted open models",
  azure: "Key and endpoint",
  custom: "OpenAI-compatible API",
};

export const PROVIDER_INITIALS: Record<ProviderType, string> = {
  openrouter: "OR",
  anthropic: "A",
  openai: "OA",
  gemini: "G",
  xai: "x",
  deepseek: "DS",
  fireworks: "F",
  novita: "N",
  azure: "AZ",
  custom: "C",
};

export const KNOWN_PROVIDER_TYPES: ProviderType[] = [
  "gemini",
  "anthropic",
  "openai",
  "xai",
  "deepseek",
  "fireworks",
  "novita",
];

export const BASE_URL_PROVIDER_TYPES: ProviderType[] = ["azure", "custom"];

export const BASE_URL_HINTS: Partial<Record<ProviderType, string>> = {
  azure: "The resource endpoint, such as https://<resource>.openai.azure.com",
  custom: "The OpenAI-compatible API base, such as https://models.example.com/v1",
};

export const MASKED_KEY_PREFIX = "*******";

export const OPENROUTER_MASKED_KEY_PREFIX = "sk-*******";

export const MAX_MODELS_PER_CONNECTION = 50;

export const AZURE_DEPLOYMENT_PATTERN = /^[A-Za-z0-9._-]{1,64}$/;

export const TYPED_PRICE_PATTERN = /^\d{1,12}(\.\d{1,12})?$/;

export const PRICE_FIELDS = [
  { field: "inputCostPerToken", column: "Input" },
  { field: "outputCostPerToken", column: "Output" },
  { field: "cacheReadInputTokenCost", column: "Cache read" },
  { field: "cacheCreationInputTokenCost", column: "Cache write" },
] as const satisfies readonly { field: PriceField; column: string }[];

export const POSITIVE_PRICE_FIELDS: readonly PriceField[] = ["inputCostPerToken", "outputCostPerToken"];
