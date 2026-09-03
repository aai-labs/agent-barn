"use client";

import { useInfiniteQuery } from "@tanstack/react-query";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { api } from "@/shared/api";

import {
  PaginatedCostRecordsSchema,
  type PaginatedCostRecords,
} from "../schemas";
import {
  COSTS_PAGE_SIZE,
  costFilterParams,
  costKey,
  mergeCostPages,
  type CostFilters,
} from "../utils";

export function useCosts(filters: CostFilters) {
  const orgApiBase = useOrganizationApiBase();
  const query = useInfiniteQuery({
    queryKey: costKey.list({ scope: { mode: "infinite" }, filters }),
    queryFn: async ({ pageParam }) => {
      const params = costFilterParams(filters);
      params.set("page", String(pageParam));
      params.set("page_size", String(COSTS_PAGE_SIZE));
      const response = await api.get<PaginatedCostRecords>(
        `${orgApiBase}/costs?${params.toString()}`,
        { schema: PaginatedCostRecordsSchema },
      );
      return response.data;
    },
    initialPageParam: 1,
    getNextPageParam: (lastPage) => {
      const nextPage = lastPage.page + 1;
      return nextPage <= Math.ceil(lastPage.total / lastPage.pageSize)
        ? nextPage
        : undefined;
    },
  });

  return {
    records: mergeCostPages(query.data?.pages ?? []),
    total: query.data?.pages[0]?.total ?? 0,
    isLoading: query.isPending,
    isFetchingNextPage: query.isFetchingNextPage,
    isFetchingNextPageError: query.isFetchNextPageError,
    hasNextPage: query.hasNextPage,
    fetchNextPage: query.fetchNextPage,
    error: query.error,
    refetch: query.refetch,
  };
}
