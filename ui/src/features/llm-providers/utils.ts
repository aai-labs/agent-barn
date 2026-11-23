import { ApiError } from "@/shared/api/error/errors";
import { getErrorDisplay } from "@/shared/api/error/get-error-display";

import {
  BASE_URL_PROVIDER_TYPES,
  POSITIVE_PRICE_FIELDS,
  PRICE_FIELDS,
  PROVIDER_TYPE_LABELS,
  TYPED_PRICE_PATTERN,
} from "./constants";
import type { LlmProviderCatalogueEntry, LlmProviderConnection, ModelPrices } from "./schemas";

const MILLION_DIGITS = 6;

export const EMPTY_TYPED_PRICES: ModelPrices = {
  inputCostPerToken: "",
  outputCostPerToken: "",
  cacheReadInputTokenCost: "",
  cacheCreationInputTokenCost: "",
};

function normalized(value: string): string {
  const [whole, fraction = ""] = value.split(".");
  const integer = whole.replace(/^0+(?=\d)/, "");
  const rest = fraction.replace(/0+$/, "");
  return rest ? `${integer}.${rest}` : integer;
}

export function perMillion(price: string): string {
  const [whole, fraction = ""] = price.split(".");
  const digits = fraction.padEnd(MILLION_DIGITS, "0");
  return normalized(`${whole}${digits.slice(0, MILLION_DIGITS)}.${digits.slice(MILLION_DIGITS)}`);
}

export function perToken(perMillionPrice: string): string {
  const [whole, fraction = ""] = perMillionPrice.split(".");
  const digits = whole.padStart(MILLION_DIGITS + 1, "0");
  return normalized(`${digits.slice(0, -MILLION_DIGITS)}.${digits.slice(-MILLION_DIGITS)}${fraction}`);
}

export function samePrice(left: string, right: string): boolean {
  return normalized(left) === normalized(right);
}

export function samePrices(left: ModelPrices, right: ModelPrices): boolean {
  return PRICE_FIELDS.every(({ field }) => samePrice(left[field], right[field]));
}

export function listedPrices(entry: LlmProviderCatalogueEntry): ModelPrices | null {
  const { inputCostPerToken, outputCostPerToken, cacheReadInputTokenCost, cacheCreationInputTokenCost } = entry;
  if (
    inputCostPerToken === null ||
    outputCostPerToken === null ||
    cacheReadInputTokenCost === null ||
    cacheCreationInputTokenCost === null
  )
    return null;
  return { inputCostPerToken, outputCostPerToken, cacheReadInputTokenCost, cacheCreationInputTokenCost };
}

export function typedPricesOf(prices: ModelPrices): ModelPrices {
  return {
    inputCostPerToken: perMillion(prices.inputCostPerToken),
    outputCostPerToken: perMillion(prices.outputCostPerToken),
    cacheReadInputTokenCost: perMillion(prices.cacheReadInputTokenCost),
    cacheCreationInputTokenCost: perMillion(prices.cacheCreationInputTokenCost),
  };
}

export function typedPriceValid(field: keyof ModelPrices, value: string): boolean {
  const price = value.trim();
  if (!TYPED_PRICE_PATTERN.test(price)) return false;
  return !POSITIVE_PRICE_FIELDS.includes(field) || /[1-9]/.test(price);
}

export function typedPricesValid(typed: ModelPrices): boolean {
  return PRICE_FIELDS.every(({ field }) => typedPriceValid(field, typed[field]));
}

export function perTokenPrices(typed: ModelPrices): ModelPrices {
  return {
    inputCostPerToken: perToken(typed.inputCostPerToken.trim()),
    outputCostPerToken: perToken(typed.outputCostPerToken.trim()),
    cacheReadInputTokenCost: perToken(typed.cacheReadInputTokenCost.trim()),
    cacheCreationInputTokenCost: perToken(typed.cacheCreationInputTokenCost.trim()),
  };
}

export function providerTitle(connection: Pick<LlmProviderConnection, "name" | "providerType">): string {
  return BASE_URL_PROVIDER_TYPES.includes(connection.providerType)
    ? connection.name
    : PROVIDER_TYPE_LABELS[connection.providerType];
}

export function failureMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 404 && error.message) return error.message;
  return getErrorDisplay(error).description;
}
