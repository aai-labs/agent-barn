"use client";

import { useQuery } from "@tanstack/react-query";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { api } from "@/shared/api";

import { MonthlyCostListSchema, type MonthlyCost } from "../schemas";
import { costKey, monthlyCostParams, type CostFilters } from "../utils";

/** Calendar-month totals for the Organization, under the page's filters.
 *
 *  Keyed on the params actually sent rather than the whole filter object, so
 *  moving the date range — which this read ignores — does not refetch it. */
export function useMonthlyCosts(filters: CostFilters) {
  const orgApiBase = useOrganizationApiBase();
  const params = monthlyCostParams(filters);
  const query = useQuery({
    queryKey: costKey.list({
      scope: { view: "monthly" },
      filters: { params: params.toString() },
    }),
    queryFn: async () => {
      const response = await api.get<MonthlyCost[]>(
        `${orgApiBase}/costs/monthly?${params.toString()}`,
        { schema: MonthlyCostListSchema },
      );
      return response.data;
    },
  });

  return {
    months: query.data ?? null,
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}
