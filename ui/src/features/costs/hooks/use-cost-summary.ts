import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { createQueryKeyStructure } from "@/shared/query-keys";
import { costSummarySchema, type CostSummary } from "../schemas";

export const costKey = createQueryKeyStructure("cost");

interface UseCostSummaryOptions {
  startDate?: string;
  endDate?: string;
}

export function useCostSummary({ startDate, endDate }: UseCostSummaryOptions = {}) {
  const orgApiBase = useOrganizationApiBase();
  const params = new URLSearchParams();
  if (startDate) params.set("start_date", startDate);
  if (endDate) params.set("end_date", endDate);
  const queryString = params.toString();

  const query = useQuery({
    queryKey: costKey.detail(`${startDate ?? "all"}-${endDate ?? "all"}`),
    queryFn: () =>
      api.get<CostSummary>(
        `${orgApiBase}/costs/summary${queryString ? `?${queryString}` : ""}`,
        { schema: costSummarySchema }
      ),
  });

  return {
    summary: query.data?.data ?? null,
    isLoadingSummary: query.isLoading,
    error: query.error,
    refetch: query.refetch,
  };
}
