import { createQueryKeyStructure } from "@/shared/query-keys";

import type {
  CostRecord,
  CostSortDirection,
  PaginatedCostRecords,
  PaginatedPlatformCostRecords,
  PlatformCostRecord,
} from "./schemas";

export const COSTS_PAGE_SIZE = 50;

// Every org-scoped cost query hangs off the single "cost" base key, distinguished
// by scope rather than by its own key. ORG_SCOPED_QUERY_KEYS matches the base key
// exactly, so a separate "cost-summary" key would quietly survive an org switch and
// render the previous organization's spend.
export const costKey = createQueryKeyStructure("cost");

// The platform key is deliberately absent from ORG_SCOPED_QUERY_KEYS: platform data
// is not org-scoped and must survive a switch.
export const platformCostKey = createQueryKeyStructure("platform-cost");

export type CostFilters = {
  organizationId?: string;
  agentId?: string;
  model?: string;
  search?: string;
  sort: CostSortDirection;
  period?: string;
  fromDate?: string;
  toDate?: string;
};

/** Build the query string every cost endpoint accepts.
 *
 *  One builder for the summary, the rows and the filter options, because the
 *  server applies the same predicate to all three — if they disagreed here, a
 *  stat card and the table beneath it would describe different sets of calls. */
export function costFilterParams(filters: CostFilters): URLSearchParams {
  const params = new URLSearchParams();
  params.set("sort", filters.sort);
  if (filters.organizationId)
    params.set("organization_id", filters.organizationId);
  if (filters.agentId) params.set("agent_id", filters.agentId);
  if (filters.model) params.set("model", filters.model);
  if (filters.search) params.set("search", filters.search);
  if (filters.fromDate) params.set("from_date", filters.fromDate);
  if (filters.toDate) params.set("to_date", filters.toDate);
  // A preset and an explicit range are mutually exclusive server-side: either
  // bound switches to a custom range and the period is ignored.
  if (filters.period && !filters.fromDate && !filters.toDate)
    params.set("period", filters.period);
  return params;
}

/**
 * Offset pagination can overlap when the sync job writes rows between page
 * reads. Keep the most recently read representation of a request, but expose
 * one row per request so React never sees a duplicate key.
 */
export function mergeCostPages(
  pages: readonly PaginatedCostRecords[],
): CostRecord[] {
  return dedupeByRequestId(pages);
}

export function mergePlatformCostPages(
  pages: readonly PaginatedPlatformCostRecords[],
): PlatformCostRecord[] {
  return dedupeByRequestId(pages);
}

function dedupeByRequestId<T extends { requestId: string }>(
  pages: readonly { items: T[] }[],
): T[] {
  const byRequestId = new Map<string, T>();
  for (const page of pages) {
    for (const record of page.items) {
      byRequestId.set(record.requestId, record);
    }
  }
  return [...byRequestId.values()];
}
