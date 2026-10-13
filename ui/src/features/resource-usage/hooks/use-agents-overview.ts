"use client";

import { useQuery } from "@tanstack/react-query";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { api } from "@/shared/api";

import { AgentOverviewSchema, type AgentOverview } from "../schemas";
import {
  RESOURCE_USAGE_REFETCH_MS,
  resourceUsageKey,
  type OverviewPeriod,
} from "../utils";

/**
 * Every Agent the caller can read, with status, spend over the period, and current
 * CPU and memory. Each figure the caller may not see comes back null, per Agent.
 */
export function useAgentsOverview(period: OverviewPeriod) {
  const orgApiBase = useOrganizationApiBase();
  const query = useQuery({
    queryKey: resourceUsageKey.overview(period),
    queryFn: async () => {
      const response = await api.get<AgentOverview>(
        `${orgApiBase}/agent-overview?period=${period}`,
        { schema: AgentOverviewSchema },
      );
      return response.data;
    },
    refetchInterval: RESOURCE_USAGE_REFETCH_MS,
  });

  return {
    overview: query.data ?? null,
    isLoadingOverview: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}
