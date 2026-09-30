"use client";

import { useQuery } from "@tanstack/react-query";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { api } from "@/shared/api";

import { GroupMemoryCostListSchema, type GroupMemoryCost } from "../schemas";
import { costFilterParams, costKey, type CostFilters } from "../utils";

/**
 * This org's memory spend split across its memory groups (pools).
 *
 * Memory is billed on Honcho's one credential with no per-agent attribution, so
 * the group is the finest meaningful split; the server apportions the total by
 * per-pool token share. Only the window matters — agent/model filters don't apply
 * to pooled memory — but we key on the whole filter set so it stays in step with
 * the rest of the page.
 */
export function useMemoryCostByGroup(filters: CostFilters, enabled = true) {
  const orgApiBase = useOrganizationApiBase();
  const query = useQuery({
    queryKey: costKey.list({ scope: { view: "memory-by-group" }, filters }),
    queryFn: async () => {
      const response = await api.get<GroupMemoryCost[]>(
        `${orgApiBase}/costs/memory-by-group?${costFilterParams(filters).toString()}`,
        { schema: GroupMemoryCostListSchema },
      );
      return response.data;
    },
    enabled,
  });

  return {
    groups: query.data ?? [],
    isLoading: query.isPending,
    error: query.error,
  };
}
