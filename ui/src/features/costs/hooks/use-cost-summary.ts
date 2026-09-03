"use client";

import { useQuery } from "@tanstack/react-query";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { api } from "@/shared/api";

import { CostSummarySchema, type CostSummary } from "../schemas";
import { costFilterParams, costKey, type CostFilters } from "../utils";

export function useCostSummary(filters: CostFilters) {
  const orgApiBase = useOrganizationApiBase();
  const query = useQuery({
    queryKey: costKey.list({ scope: { view: "summary" }, filters }),
    queryFn: async () => {
      const response = await api.get<CostSummary>(
        `${orgApiBase}/costs/summary?${costFilterParams(filters).toString()}`,
        { schema: CostSummarySchema },
      );
      return response.data;
    },
  });

  return {
    summary: query.data ?? null,
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}
