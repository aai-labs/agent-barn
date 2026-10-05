"use client";

import { useQuery } from "@tanstack/react-query";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { api } from "@/shared/api";

import { PaginatedMemoryItemsSchema, type PaginatedMemoryItems } from "../schemas";
import { MEMORY_ITEMS_PAGE_SIZE, agentMemoryKey, organizationMemoryKey } from "../utils";

/**
 * permission-scoped Agent memory or shared Organization Memory. The caller must pass the matching
 * human viewing permission so unauthorized people never issue the request.
 */
export function useMemoryItems(
  agentId: string | undefined,
  { search, page, enabled }: { search: string; page: number; enabled: boolean },
) {
  const orgApiBase = useOrganizationApiBase();
  const queryKey = agentId
    ? agentMemoryKey.items(orgApiBase, agentId, { search, page })
    : organizationMemoryKey.items(orgApiBase, { search, page });

  const query = useQuery({
    queryKey,
    queryFn: async () => {
      const params = new URLSearchParams();
      params.set("page", String(page));
      params.set("page_size", String(MEMORY_ITEMS_PAGE_SIZE));
      if (search) params.set("search", search);
      const response = await api.get<PaginatedMemoryItems>(
        `${orgApiBase}${agentId ? `/agents/${agentId}` : ""}/memory/items?${params.toString()}`,
        { schema: PaginatedMemoryItemsSchema },
      );
      return response.data;
    },
    enabled,
    // Keep pages only within the same Agent and Organization. An observer may
    // survive navigation; its previous data must not follow it to another target.
    placeholderData: (previousData, previousQuery) =>
      queryKey.slice(0, -1).every((part, index) => previousQuery?.queryKey[index] === part)
        ? previousData
        : undefined,
    refetchInterval: agentId ? 60_000 : false,
    refetchOnWindowFocus: true,
    retry: false,
  });

  return {
    items: query.data?.items ?? [],
    total: query.data?.total ?? 0,
    isLoading: query.isPending && query.fetchStatus !== "idle",
    isFetching: query.isFetching,
    error: query.error,
    refetch: query.refetch,
  };
}
