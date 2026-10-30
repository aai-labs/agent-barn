import type { UsageDates } from "./utils";

const KIB = 1024;
const MIB = KIB * 1024;
const GIB = MIB * 1024;

/** Memory the way an operator reads it: binary units, as the limit is set in them. */
export function formatBytes(value: number): string {
  if (value >= GIB) return `${Number((value / GIB).toFixed(2))} GiB`;
  if (value >= MIB) return `${Math.round(value / MIB)} MiB`;
  if (value >= KIB) return `${Math.round(value / KIB)} KiB`;
  return `${Math.round(value)} B`;
}

/** CPU in cores. Two decimals, and "<0.01" rather than a misleading zero for a nearly idle container. */
export function formatCores(value: number): string {
  if (value > 0 && value < 0.01) return "<0.01";
  return String(Number(value.toFixed(2)));
}

/** A share of time for an axis or tooltip. One decimal below 10%, where whole numbers
 *  would round 2.5% to 3% and make a small axis read wrong. */
export function formatShare(fraction: number): string {
  return `${Number((fraction * 100).toFixed(fraction < 0.1 ? 1 : 0))}%`;
}

const DAY_SECONDS = 24 * 3600;

/** Local time, because "the last hour" is read against the reader's own clock. The cost
 *  charts use UTC since they bucket by calendar day; these are instants. */
export function formatUsageTick(iso: string, spanSeconds: number): string {
  const date = new Date(iso);
  if (spanSeconds > 7 * DAY_SECONDS) {
    return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }
  if (spanSeconds > DAY_SECONDS) {
    return date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric" });
  }
  return date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

/** How long a window is, for a short label: "24h", "7d". A window that ends now covers
 *  part of today, so days round up and count the calendar days it touches. */
export function formatUsageSpan(fromIso: string, toIso: string): string {
  const hours = Math.round((new Date(toIso).getTime() - new Date(fromIso).getTime()) / 3_600_000);
  return hours < 48 ? `${hours}h` : `${Math.ceil(hours / 24)}d`;
}

/** The picked days for a sentence, or `fallback` while none are picked. */
export function formatUsageDates(dates: UsageDates, fallback: string): string {
  if (!dates.from) return fallback;
  const day = (iso: string) => new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  return dates.to ? `${day(dates.from)} – ${day(dates.to)}` : `since ${day(dates.from)}`;
}

export function formatUsageTooltipTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}
