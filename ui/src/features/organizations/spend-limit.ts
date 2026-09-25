/** Formatting shared by every surface that shows a model spend limit. */

export const SPEND_LIMIT_WINDOWS = [
  { value: "1d", label: "per day", period: "today" },
  // Renews each Monday.
  { value: "7d", label: "per week", period: "this week" },
  // Renews on the 1st of each month, not every 30 days from when it was set.
  { value: "30d", label: "per month", period: "this month" },
] as const;

export const DEFAULT_SPEND_LIMIT_WINDOW = "30d";

export function windowLabel(value: string | null | undefined) {
  return SPEND_LIMIT_WINDOWS.find((option) => option.value === value)?.label ?? "";
}

/** "this month" for a monthly limit — the period spend so far is counted over. */
export function periodLabel(value: string | null | undefined) {
  return SPEND_LIMIT_WINDOWS.find((option) => option.value === value)?.period ?? "so far";
}

/** Both halves of "X of Y used" share a precision chosen from the limit. Formatting
 *  them independently renders 0.011985 against a 0.01 cap as "$0.01 of $0.01", which
 *  hides the overshoot at exactly the point it matters. */
export function usdDigits(limit: number) {
  return limit > 0 && limit < 1 ? 4 : 2;
}

export function formatUsd(value: number, digits = usdDigits(value)) {
  return `$${value.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

/** "$12.50 of $50.00", both halves at the limit's precision. */
export function formatUsage(spend: number, limit: number) {
  const digits = usdDigits(limit);
  return `${formatUsd(spend, digits)} of ${formatUsd(limit, digits)}`;
}

export function formatRenewal(iso: string) {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

/** Parses a typed amount: null for empty, NaN for anything that is not a finite
 *  non-negative number, so callers can tell "cleared" from "invalid". */
export function parseAmount(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : Number.NaN;
}

/** Every spend-limit query, whichever feature owns it: a change at one level can move
 *  the limits at every level beneath it. */
export function isSpendLimitQuery(queryKey: readonly unknown[]) {
  return queryKey.some((part) => typeof part === "string" && part.startsWith("llm-budget"));
}

/** One validation rule for every amount field. `required` is for limits that can't
 *  be cleared back to something they inherit. */
export function amountError(raw: string, { required = false, max }: { required?: boolean; max?: number } = {}) {
  const parsed = parseAmount(raw);
  if (parsed === null) return required ? "Enter an amount of zero or more." : null;
  if (Number.isNaN(parsed)) return "Enter an amount of zero or more.";
  if (max !== undefined && parsed > max) return `This can't be more than ${formatUsd(max, usdDigits(max))}.`;
  return null;
}

/** Said beside an amount of exactly zero, which is allowed but stops everything it
 *  applies to. */
export function zeroNotice(raw: string, subject: string) {
  return parseAmount(raw) === 0 ? `At $0, ${subject} can't make any model calls.` : null;
}
