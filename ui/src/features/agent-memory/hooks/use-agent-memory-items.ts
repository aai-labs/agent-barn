"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { api } from "@/shared/api";

import { PaginatedMemoryItemsSchema, type PaginatedMemoryItems } from "../schemas";
import { MEMORY_ITEMS_PAGE_SIZE, agentMemoryKey } from "../utils";

/**
 * The memories one Agent wrote. `enabled` must carry the viewer's `activity.read`
 * permission, so a person without it never issues the request.
 */
export function useAgentMemoryItems(
  agentId: string,
  { search, page, enabled }: { search: string; page: number; enabled: boolean },
) {
  const orgApiBase = useOrganizationApiBase();

  const query = useQuery({
    queryKey: agentMemoryKey.items(orgApiBase, agentId, { search, page }),
    queryFn: async () => {
      const params = new URLSearchParams();
      params.set("page", String(page));
      params.set("page_size", String(MEMORY_ITEMS_PAGE_SIZE));
      if (search) params.set("search", search);
      const response = await api.get<PaginatedMemoryItems>(
        `${orgApiBase}/agents/${agentId}/memory/items?${params.toString()}`,
        { schema: PaginatedMemoryItemsSchema },
      );
      return response.data;
    },
    enabled: enabled && !!agentId,
    // Keep the previous page on screen while the next one loads.
    placeholderData: keepPreviousData,
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
