"use client";

import { useQuery } from "@tanstack/react-query";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { api } from "@/shared/api";

import { useCatchUpWhenPolling } from "./use-catch-up-when-polling";

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
 * `error` only means the request itself failed: no access, or the API is down. It
 * refreshes every minute while `poll` holds; a list row passes whether it is on screen.
 */
export function useAgentResourceUsage(
  agentId: string,
  range: ResourceUsageRange,
  enabled = true,
  { poll = true }: { poll?: boolean } = {},
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
    refetchInterval: poll ? RESOURCE_USAGE_REFETCH_MS : false,
    // A 403 or 404 will not change on a second try.
    retry: false,
  });
  useCatchUpWhenPolling(query, poll && enabled && !!agentId, RESOURCE_USAGE_REFETCH_MS);

  return {
    usage: query.data ?? null,
    isLoadingUsage: query.isPending,
    isFetching: query.isFetching,
    error: query.error,
    refetch: query.refetch,
  };
}
