"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { PlatformAgentDetailsSchema, type PlatformAgentDetails } from "../schemas";
import { RESOURCE_USAGE_REFETCH_MS, resourceUsageKey, usageDateParams, type UsageDates } from "../utils";

/**
 * Status and usage over the page's days for one Agent, for a Heaviest agents row that is open.
 *
 * Platform Administrators only. It is mounted with the opened row and unmounts with it, so
 * a closed row costs no request, and an open one refreshes on the same minute as the page.
 * Status rides on the same request, so picking other days keeps the last answer on screen
 * instead of blanking both panels while the new days load.
 */
export function usePlatformAgentDetails(agentId: string, dates: UsageDates) {
  const query = useQuery({
    queryKey: resourceUsageKey.platformAgent(agentId, dates),
    queryFn: async () => {
      const response = await api.get<PlatformAgentDetails>(
        `/api/v1/platform/resource-usage/agents/${agentId}?${usageDateParams(dates).toString()}`,
        { schema: PlatformAgentDetailsSchema },
      );
      return response.data;
    },
    refetchInterval: RESOURCE_USAGE_REFETCH_MS,
    placeholderData: keepPreviousData,
  });

  return {
    details: query.data ?? null,
    isLoadingDetails: query.isPending,
    error: query.error,
  };
}
