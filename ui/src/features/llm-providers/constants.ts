import type { ProviderType } from "./schemas";

export const PROVIDER_TYPE_LABELS: Record<ProviderType, string> = {
  openrouter: "OpenRouter",
  anthropic: "Anthropic",
  openai: "OpenAI",
  gemini: "Gemini",
  xai: "xAI",
  deepseek: "DeepSeek",
  fireworks: "Fireworks",
  novita: "Novita",
  azure: "Azure",
  custom: "Custom (OpenAI-compatible)",
};

export const KNOWN_PROVIDER_TYPES: ProviderType[] = [
  "anthropic",
  "openai",
  "gemini",
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
