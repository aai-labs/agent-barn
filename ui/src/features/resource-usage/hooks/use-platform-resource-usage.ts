"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { PlatformResourceUsageSchema, type PlatformResourceUsage, type ResourceUsageRange } from "../schemas";
import { RESOURCE_USAGE_REFETCH_MS, resourceUsageKey } from "../utils";

/**
 * CPU and memory of every Agent's container across all Organizations, or one
 * Organization's when it is given. Platform Administrators only.
 */
export function usePlatformResourceUsage(range: ResourceUsageRange, organizationId: string | null) {
  const query = useQuery({
    queryKey: resourceUsageKey.platform(range, organizationId),
    queryFn: async () => {
      const params = new URLSearchParams({ range });
      if (organizationId) params.set("organization_id", organizationId);
      const response = await api.get<PlatformResourceUsage>(
        `/api/v1/platform/resource-usage?${params.toString()}`,
        { schema: PlatformResourceUsageSchema },
      );
      return response.data;
    },
    refetchInterval: RESOURCE_USAGE_REFETCH_MS,
  });

  return {
    usage: query.data ?? null,
    isLoadingUsage: query.isPending,
    isFetching: query.isFetching,
    error: query.error,
    refetch: query.refetch,
  };
}
