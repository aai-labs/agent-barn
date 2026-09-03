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

/** Whole dollars stay whole: "$1", not "$1.00", when the axis is this tight. */
function formatDollarsTerse(value: number): string {
  return `$${value % 1 === 0 ? value : value.toFixed(2)}`;
}

/** The same band, shortened until nine of them fit across a half-width card.
 *
 *  Two things buy the space. A band is fully described by its top edge, so the
 *  lower bound goes — it is the previous tick. And below a dollar the label
 *  switches to cents, where "0.1¢" says in four characters what "$0.001" needs
 *  six to say, and the sub-cent end stops being a row of zeros to count.
 *
 *  "≤" is what keeps a bare edge from reading as the band's midpoint. The
 *  tooltip still gives the exact range, so nothing is lost by shortening here. */
export function formatHistogramTick(lower: number, upper: number | null): string {
  if (upper === null) return `>${formatDollarsTerse(lower)}`;
  if (upper >= 1) return `≤${formatDollarsTerse(upper)}`;
  const cents = upper * 100;
  // toFixed then back through Number drops the float dust: 0.0001 * 100 is
  // 0.010000000000000002, which would otherwise print in full.
  return `≤${Number(cents.toFixed(2))}¢`;
}

export function formatDuration(ms: number | null): string {
  if (ms === null) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}
