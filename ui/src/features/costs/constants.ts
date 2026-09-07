import type { CostSortDirection } from "./schemas";

export const COST_SORT_LABELS: Record<CostSortDirection, string> = {
  newest_first: "Newest first",
  oldest_first: "Oldest first",
  most_expensive: "Most expensive",
};

// The period presets are gone: the cost surfaces pick an explicit start and end
// instead. With neither bound set the server still applies its own default
// window, so an unfiltered page keeps working with a clean URL.
