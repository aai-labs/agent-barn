import type { CostSortDirection } from "./schemas";

export const COST_SORT_LABELS: Record<CostSortDirection, string> = {
  newest_first: "Newest first",
  oldest_first: "Oldest first",
  most_expensive: "Most expensive",
};

/** Reporting presets the server accepts. Kept in this order because the picker
 *  renders them in it. */
export const COST_PERIODS = [
  { value: "SEVEN_DAYS", label: "Last 7 days" },
  { value: "THIRTY_DAYS", label: "Last 30 days" },
  { value: "NINETY_DAYS", label: "Last 90 days" },
] as const;

export const DEFAULT_COST_PERIOD = "THIRTY_DAYS";
