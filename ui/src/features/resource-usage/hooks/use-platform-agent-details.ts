"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { PlatformAgentDetailsSchema, type PlatformAgentDetails } from "../schemas";
import { RESOURCE_USAGE_REFETCH_MS, resourceUsageKey } from "../utils";

/**
 * Status and last-day usage for one Agent, for a Heaviest agents row that is open.
 *
 * Platform Administrators only. It is mounted with the opened row and unmounts with it, so
 * a closed row costs no request, and an open one refreshes on the same minute as the page.
 */
export function usePlatformAgentDetails(agentId: string) {
  const query = useQuery({
    queryKey: resourceUsageKey.platformAgent(agentId),
    queryFn: async () => {
      const response = await api.get<PlatformAgentDetails>(
        `/api/v1/platform/resource-usage/agents/${agentId}`,
        { schema: PlatformAgentDetailsSchema },
      );
      return response.data;
    },
    refetchInterval: RESOURCE_USAGE_REFETCH_MS,
  });

  return {
    details: query.data ?? null,
    isLoadingDetails: query.isPending,
    error: query.error,
  };
}
