"use client";

import { useInfiniteQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { createQueryKeyStructure } from "@/shared/query-keys";

import {
  PaginatedPlatformCreditRecordsSchema,
  type CreditKind,
  type PaginatedPlatformCreditRecords,
} from "../schemas";

export const platformCreditHistoryKey = createQueryKeyStructure("platform-credit-history");

const PAGE_SIZE = 50;

export interface PlatformCreditHistoryFilters {
  kind: CreditKind | null;
  organizationId: string | null;
}

/** Every organization's changes to its credit, newest first, a page at a time. */
export function usePlatformCreditHistory(filters: PlatformCreditHistoryFilters) {
  const query = useInfiniteQuery({
    queryKey: platformCreditHistoryKey.list({ filters }),
    queryFn: async ({ pageParam }) => {
      const params = new URLSearchParams({ page: String(pageParam), page_size: String(PAGE_SIZE) });
      if (filters.kind) params.set("kind", filters.kind);
      if (filters.organizationId) params.set("organization_id", filters.organizationId);
      return (
        await api.get<PaginatedPlatformCreditRecords>(`/api/v1/platform/billing/credit-history?${params}`, {
          schema: PaginatedPlatformCreditRecordsSchema,
        })
      ).data;
    },
    initialPageParam: 1,
    getNextPageParam: (lastPage) =>
      lastPage.page * lastPage.pageSize < lastPage.total ? lastPage.page + 1 : undefined,
  });

  return {
    records: query.data?.pages.flatMap((page) => page.items) ?? [],
    total: query.data?.pages[0]?.total ?? 0,
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
    hasNextPage: query.hasNextPage,
    fetchNextPage: query.fetchNextPage,
    isFetchingNextPage: query.isFetchingNextPage,
  };
}
