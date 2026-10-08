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
 *  The edge carries no "≤": Geist has no glyph at U+2264, so the browser drew
 *  that one character in a fallback face and every label on the axis looked like
 *  a different font. The chart's subtitle says the labels are upper bounds, and
 *  the tooltip still gives each band's exact range. */
export function formatHistogramTick(lower: number, upper: number | null): string {
  if (upper === null) return `>${formatDollarsTerse(lower)}`;
  if (upper >= 1) return formatDollarsTerse(upper);
  const cents = upper * 100;
  // toFixed then back through Number drops the float dust: 0.0001 * 100 is
  // 0.010000000000000002, which would otherwise print in full.
  return `${Number(cents.toFixed(2))}¢`;
}

export function formatDuration(ms: number | null): string {
  if (ms === null) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

/** The model as the cost surfaces show it: the slug alone, without its routing path.
 *  `cost_record.model` stores the full route (e.g. "openrouter/anthropic/claude-opus-5"),
 *  which is too long to read in a table and identical across rows in its leading parts. */
export function formatModelLabel(model: string): string {
  return model.split("/").at(-1) ?? model;
}

const PERIOD_LABELS: Record<string, string> = {
  SEVEN_DAYS: "last 7 days",
  THIRTY_DAYS: "last 30 days",
  NINETY_DAYS: "last 90 days",
};

/** Names the window a figure covers.
 *
 *  Cost figures are a rolling range ending now; a spend allowance runs to its own
 *  renewal date. The two rarely line up, so both have to say which period they mean
 *  or they read as a contradiction. */
export function formatWindowLabel(
  period: string | null,
  fromDate: string,
  toDate: string,
): string {
  const named = period ? PERIOD_LABELS[period] : undefined;
  if (named) return named;
  const short = (iso: string) => {
    const date = new Date(iso);
    return Number.isNaN(date.getTime())
      ? iso
      : date.toLocaleDateString(undefined, { day: "numeric", month: "short" });
  };
  return `${short(fromDate)} – ${short(toDate)}`;
}

/** A calendar month, read in UTC: the server groups on the UTC month, and a
 *  local reading would slide the first of the month back into the previous one
 *  anywhere west of Greenwich. */
export function formatMonth(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}

/** Short month label for a chart axis. */
export function formatMonthShort(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    timeZone: "UTC",
  });
}

/** Month-over-month change. Null when there is nothing to compare against. */
export function spendChange(current: number, previous: number): number | null {
  if (previous === 0) return null;
  return (current - previous) / previous;
}

export function formatChange(change: number | null): string {
  if (change === null) return "—";
  const percent = Math.round(change * 100);
  if (percent === 0) return "0%";
  return `${percent > 0 ? "↑" : "↓"} ${Math.abs(percent)}%`;
}

export function formatPercent(fraction: number): string {
  if (fraction > 0 && fraction < 0.01) return "<1%";
  return `${Math.round(fraction * 100)}%`;
}
