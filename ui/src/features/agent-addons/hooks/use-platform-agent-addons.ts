"use client";

import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";

import {
  type AgentAddonState,
  type PaginatedPlatformAgentAddons,
  PaginatedPlatformAgentAddonsSchema,
  type PlatformAgentAddon,
  PlatformAgentAddonSchema,
} from "../schemas";
import { PLATFORM_AGENT_ADDONS_PAGE_SIZE, platformAgentAddonsKey } from "../utils";

/** Every add-on request across Organizations, newest first, a page at a time. Platform Administrators only. */
export function usePlatformAgentAddons({
  state,
  search,
  organizationId,
}: {
  state: AgentAddonState | null;
  search: string;
  organizationId: string | null;
}) {
  const trimmed = search.trim();
  const query = useInfiniteQuery({
    queryKey: platformAgentAddonsKey.list({ state, search: trimmed, organizationId }),
    queryFn: async ({ pageParam = 1 }) => {
      const params = new URLSearchParams({ page: String(pageParam), page_size: String(PLATFORM_AGENT_ADDONS_PAGE_SIZE) });
      if (state) params.set("state", state);
      if (trimmed) params.set("search", trimmed);
      if (organizationId) params.set("organization_id", organizationId);
      const response = await api.get<PaginatedPlatformAgentAddons>(
        `/api/v1/platform/agent-addons?${params.toString()}`,
        { schema: PaginatedPlatformAgentAddonsSchema },
      );
      return response.data;
    },
    initialPageParam: 1,
    getNextPageParam: (lastPage) => {
      const nextPage = lastPage.page + 1;
      return nextPage <= Math.ceil(lastPage.total / lastPage.pageSize) ? nextPage : undefined;
    },
  });

  return {
    requests: query.data?.pages.flatMap((page) => page.items) ?? [],
    total: query.data?.pages[0]?.total ?? 0,
    hasNextPage: query.hasNextPage,
    fetchNextPage: query.fetchNextPage,
    isFetchingNextPage: query.isFetchingNextPage,
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}

export type AddonDecision = { action: "approve" } | { action: "reject"; reason: string } | { action: "revoke" };

/** Approve, reject (with a reason) or revoke one request. Never restarts the Agent. */
export function useDecidePlatformAgentAddon() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ addonId, decision }: { addonId: string; decision: AddonDecision }) =>
      (
        await api.post<PlatformAgentAddon>(
          `/api/v1/platform/agent-addons/${addonId}/${decision.action}`,
          decision.action === "reject" ? { reason: decision.reason } : undefined,
          { schema: PlatformAgentAddonSchema },
        )
      ).data,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: platformAgentAddonsKey.all }),
  });
}
