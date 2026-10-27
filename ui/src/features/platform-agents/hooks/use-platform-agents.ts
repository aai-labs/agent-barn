"use client";

import { useInfiniteQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { PaginatedPlatformAgentsSchema, type PaginatedPlatformAgents } from "../schemas";
import { PLATFORM_AGENTS_PAGE_SIZE, platformAgentsKey } from "../utils";

/**
 * Every live Agent on the platform, a page at a time, ordered by Organization then name.
 * Platform Administrators only.
 */
export function usePlatformAgents({ search, organizationId }: { search: string; organizationId: string | null }) {
  const trimmed = search.trim();
  const query = useInfiniteQuery({
    queryKey: platformAgentsKey.list({ search: trimmed, organizationId }),
    queryFn: async ({ pageParam = 1 }) => {
      const params = new URLSearchParams({ page: String(pageParam), page_size: String(PLATFORM_AGENTS_PAGE_SIZE) });
      if (trimmed) params.set("search", trimmed);
      if (organizationId) params.set("organization_id", organizationId);
      const response = await api.get<PaginatedPlatformAgents>(`/api/v1/platform/agents?${params.toString()}`, {
        schema: PaginatedPlatformAgentsSchema,
      });
      return response.data;
    },
    initialPageParam: 1,
    getNextPageParam: (lastPage) => {
      const nextPage = lastPage.page + 1;
      return nextPage <= Math.ceil(lastPage.total / lastPage.pageSize) ? nextPage : undefined;
    },
  });

  return {
    agents: query.data?.pages.flatMap((page) => page.items) ?? [],
    total: query.data?.pages[0]?.total ?? 0,
    hasNextPage: query.hasNextPage,
    fetchNextPage: query.fetchNextPage,
    isFetchingNextPage: query.isFetchingNextPage,
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}
