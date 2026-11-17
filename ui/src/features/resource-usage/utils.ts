import { agentsKey } from "@/features/agents/utils";

/** Prometheus keeps 15 days, so a picked window reaches back no further. */
export const USAGE_RETENTION_DAYS = 15;

/** A picked window as ISO bounds, or "" where the page's default applies. */
export interface UsageDates {
  from: string;
  to: string;
}

/** The first day the calendar offers: it and the 14 days after it, today included, make 15. */
export function earliestUsageDay(now = new Date()): Date {
  return new Date(now.getFullYear(), now.getMonth(), now.getDate() - (USAGE_RETENTION_DAYS - 1));
}

/** The 15 days the Usage page reads when no dates are picked. */
export function lastUsageDays(now = new Date()): UsageDates {
  const endOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59, 999);
  return { from: earliestUsageDay(now).toISOString(), to: endOfToday.toISOString() };
}

export function usageDateParams(dates: UsageDates): URLSearchParams {
  const params = new URLSearchParams();
  if (dates.from) params.set("from_date", dates.from);
  if (dates.to) params.set("to_date", dates.to);
  return params;
}

/** Both figures move slowly; a minute matches how often Prometheus is worth asking. */
export const RESOURCE_USAGE_REFETCH_MS = 60_000;

/** Health is a separate request per row, so the overview polls it less often than the
 *  Agent page does. */
export const OVERVIEW_HEALTH_REFETCH_MS = 30_000;

/** A meter turns amber at this share of its limit, and red at the next. */
export const METER_WARN_RATIO = 0.75;
export const METER_CRITICAL_RATIO = 0.9;

/** Share of scheduling periods spent throttled above which the CPU limit is worth
 *  calling out. A quarter means the Agent waited for CPU one period in four. */
export const THROTTLING_WARN_RATIO = 0.25;

export type MeterTone = "ok" | "warn" | "err";

/** Value as a share of its limit, or null when either is unknown. Not clamped: the
 *  meter clamps what it draws, and the text should say what was measured. */
export function usageRatio(value: number | null, limit: number | null): number | null {
  if (value === null || limit === null || limit <= 0) return null;
  return value / limit;
}

export function meterTone(ratio: number | null): MeterTone {
  if (ratio !== null && ratio >= METER_CRITICAL_RATIO) return "err";
  if (ratio !== null && ratio >= METER_WARN_RATIO) return "warn";
  return "ok";
}

export type CapacityState = "unset" | "unknown" | "ok" | "warn" | "critical" | "over";

export interface CapacityStatus {
  state: CapacityState;
  /** Committed as a share of the limit; null while either is missing. Not clamped. */
  ratio: number | null;
}

/**
 * How close what the namespace commits is to the ceiling an administrator entered.
 *
 * Over the ceiling is its own state: the quota itself cannot be exceeded, so a figure past
 * it means the entered limit is out of date. Exactly at the ceiling is "critical".
 */
export function capacityStatus(committed: number | null, limit: number | null): CapacityStatus {
  if (limit === null || limit <= 0) return { state: "unset", ratio: null };
  if (committed === null) return { state: "unknown", ratio: null };
  const ratio = committed / limit;
  if (ratio > 1) return { state: "over", ratio };
  if (ratio >= METER_CRITICAL_RATIO) return { state: "critical", ratio };
  if (ratio >= METER_WARN_RATIO) return { state: "warn", ratio };
  return { state: "ok", ratio };
}

export const resourceUsageKey = {
  /** Under the Agent's own key, so anything that refreshes the Agent refreshes this. */
  agent: (agentId: string, dates: UsageDates) =>
    [...agentsKey.detail(agentId), "resource-usage", dates.from, dates.to] as const,
  /** Under the Agent lists, so starting, stopping or deleting one refreshes the overview. */
  overview: (dates: UsageDates) =>
    agentsKey.list({ scope: { view: "overview" }, filters: { from: dates.from, to: dates.to } }),
  /** Not under the Agent keys: it is Platform data, and no Organization's cache is its. */
  platform: (dates: UsageDates, organizationId: string | null) =>
    ["platform", "resource-usage", dates.from, dates.to, organizationId] as const,
  /** Every Platform usage query, whatever its window or filter. */
  platformAll: ["platform", "resource-usage"] as const,
  /** One opened Heaviest agents row. */
  platformAgent: (agentId: string, dates: UsageDates) =>
    ["platform", "resource-usage", "agent", agentId, dates.from, dates.to] as const,
};
