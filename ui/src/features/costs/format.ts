/** Money and token formatting for the cost surfaces.
 *
 *  Spend arrives as a float from a NUMERIC column: exact in storage, where it
 *  decides whether a row still needs healing, and rounded here, where it only
 *  has to be read. */

/** Totals and stat cards — two decimals, the way an invoice reads. */
export function formatSpend(value: number): string {
  return value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/** Per-call cost, where two decimals would round most rows to $0.00.
 *  Four significant-ish digits keep a fraction of a cent legible. */
export function formatCallSpend(value: number): string {
  if (value === 0) return "$0";
  if (value < 0.01) {
    return `$${value.toFixed(6).replace(/0+$/, "").replace(/\.$/, "")}`;
  }
  return formatSpend(value);
}

/** Axis and band labels, where space is tight. */
export function formatSpendCompact(value: number): string {
  if (value >= 1000) return `$${(value / 1000).toFixed(1)}k`;
  if (value >= 1) return `$${value.toFixed(2)}`;
  if (value === 0) return "$0";
  return `$${value.toFixed(4).replace(/0+$/, "").replace(/\.$/, "")}`;
}

export function formatTokens(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
  return Math.round(value).toLocaleString("en-US");
}

/** A histogram band, as a range a reader can say out loud. */
export function formatHistogramBand(lower: number, upper: number | null): string {
  if (upper === null) return `${formatSpendCompact(lower)}+`;
  return `${formatSpendCompact(lower)}–${formatSpendCompact(upper)}`;
}

export function formatDuration(ms: number | null): string {
  if (ms === null) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}
