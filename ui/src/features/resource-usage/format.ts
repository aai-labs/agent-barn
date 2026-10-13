import type { ResourceUsageRange } from "./schemas";

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

/** Local time, because "the last hour" is read against the reader's own clock. The cost
 *  charts use UTC since they bucket by calendar day; these are instants. */
export function formatUsageTick(iso: string, range: ResourceUsageRange): string {
  const date = new Date(iso);
  if (range === "14d") {
    return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }
  if (range === "7d") {
    return date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric" });
  }
  return date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

export function formatUsageTooltipTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}
