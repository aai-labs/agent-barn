import { agentsKey } from "@/features/agents/utils";

import type { ResourceUsageRange } from "./schemas";

/** Prometheus keeps 15 days, so the longest range is 14. */
export const RESOURCE_USAGE_RANGES: { value: ResourceUsageRange; label: string }[] = [
  { value: "1h", label: "Last hour" },
  { value: "6h", label: "Last 6 hours" },
  { value: "24h", label: "Last 24 hours" },
  { value: "7d", label: "Last 7 days" },
  { value: "14d", label: "Last 14 days" },
];

export const DEFAULT_USAGE_RANGE: ResourceUsageRange = "24h";

/** The periods the agents overview can total spend over. */
export const OVERVIEW_PERIODS = [
  { value: "SEVEN_DAYS", label: "Last 7 days" },
  { value: "THIRTY_DAYS", label: "Last 30 days" },
  { value: "NINETY_DAYS", label: "Last 90 days" },
] as const;

export type OverviewPeriod = (typeof OVERVIEW_PERIODS)[number]["value"];
export const DEFAULT_OVERVIEW_PERIOD: OverviewPeriod = "THIRTY_DAYS";

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

export const resourceUsageKey = {
  /** Under the Agent's own key, so anything that refreshes the Agent refreshes this. */
  agent: (agentId: string, range: ResourceUsageRange) =>
    [...agentsKey.detail(agentId), "resource-usage", range] as const,
  /** Under the Agent lists, so starting, stopping or deleting one refreshes the overview. */
  overview: (period: string) =>
    agentsKey.list({ scope: { view: "overview" }, filters: { period } }),
  /** Not under the Agent keys: it is Platform data, and no Organization's cache is its. */
  platform: (range: ResourceUsageRange, organizationId: string | null) =>
    ["platform", "resource-usage", range, organizationId] as const,
};
