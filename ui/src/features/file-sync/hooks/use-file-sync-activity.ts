"use client";

import { useInfiniteQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";

import { AgentFileSyncActivityPageSchema, type AgentFileSyncActivityPage } from "../schemas";
import { fileSyncActivityKey } from "../utils";

export const FILE_SYNC_ACTIVITY_PAGE_SIZE = 20;

export function useFileSyncActivity(agentId: string, enabled = true) {
  const orgApiBase = useOrganizationApiBase();
  const { selectedOrganization } = useOrganizationContext();
  const organizationId = selectedOrganization?.id ?? "";

  const query = useInfiniteQuery({
    queryKey: fileSyncActivityKey(organizationId, agentId),
    initialPageParam: 1,
    queryFn: async ({ pageParam }) => {
      const response = await api.get<AgentFileSyncActivityPage>(
        `${orgApiBase}/agents/${agentId}/file-sync/activity?page=${pageParam}&page_size=${FILE_SYNC_ACTIVITY_PAGE_SIZE}`,
        { schema: AgentFileSyncActivityPageSchema },
      );
      return response.data;
    },
    getNextPageParam: (lastPage) =>
      lastPage.page * lastPage.pageSize < lastPage.total ? lastPage.page + 1 : undefined,
    enabled: enabled && Boolean(organizationId) && Boolean(agentId),
  });

  return {
    entries: query.data?.pages.flatMap((page) => page.items) ?? [],
    isLoadingEntries: query.isPending,
    error: query.error,
    refetch: query.refetch,
    hasMore: query.hasNextPage,
    loadMore: query.fetchNextPage,
    isLoadingMore: query.isFetchingNextPage,
  };
}
