import { ApiError } from "@/shared/api/error/errors";
import { getErrorDisplay } from "@/shared/api/error/get-error-display";

const MILLION_DIGITS = 6;

export function perMillion(price: string): string {
  const [whole, fraction = ""] = price.split(".");
  const digits = fraction.padEnd(MILLION_DIGITS, "0");
  const integer = `${whole}${digits.slice(0, MILLION_DIGITS)}`.replace(/^0+(?=\d)/, "");
  const rest = digits.slice(MILLION_DIGITS).replace(/0+$/, "");
  return rest ? `${integer}.${rest}` : integer;
}

export function failureMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 404 && error.message) return error.message;
  return getErrorDisplay(error).description;
}
