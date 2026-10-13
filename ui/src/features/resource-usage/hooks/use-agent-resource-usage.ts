"use client";

import { useQuery } from "@tanstack/react-query";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { api } from "@/shared/api";

import {
  AgentResourceUsageSchema,
  type AgentResourceUsage,
  type ResourceUsageRange,
} from "../schemas";
import { RESOURCE_USAGE_REFETCH_MS, resourceUsageKey } from "../utils";

/**
 * One Agent's CPU and memory, now and across a range.
 *
 * A source that cannot be reached is an answer (`availability`), not an error, so
 * `error` only means the request itself failed: no access, or the API is down.
 */
export function useAgentResourceUsage(
  agentId: string,
  range: ResourceUsageRange,
  enabled = true,
) {
  const orgApiBase = useOrganizationApiBase();
  const query = useQuery({
    queryKey: resourceUsageKey.agent(agentId, range),
    queryFn: async () => {
      const response = await api.get<AgentResourceUsage>(
        `${orgApiBase}/agents/${agentId}/resource-usage?range=${range}`,
        { schema: AgentResourceUsageSchema },
      );
      return response.data;
    },
    enabled: enabled && !!agentId,
    refetchInterval: RESOURCE_USAGE_REFETCH_MS,
    // A 403 or 404 will not change on a second try.
    retry: false,
  });

  return {
    usage: query.data ?? null,
    isLoadingUsage: query.isPending,
    isFetching: query.isFetching,
    error: query.error,
    refetch: query.refetch,
  };
}
