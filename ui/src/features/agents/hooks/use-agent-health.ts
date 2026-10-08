"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import { AgentHealth, AgentHealthSchema } from "../schemas";
import { agentsKey } from "../utils";

const DEFAULT_HEALTH_REFETCH_MS = 10_000;

/** `refetchIntervalMs` is for lists: each row polls on its own, so they poll slower than
 *  the Agent page, where one Agent is on screen. */
export function useAgentHealth(
  agentId: string,
  enabled: boolean,
  refetchIntervalMs: number = DEFAULT_HEALTH_REFETCH_MS,
) {
  const orgApiBase = useOrganizationApiBase();
  const query = useQuery({
    queryKey: agentsKey.health(agentId),
    queryFn: async () => {
      const response = await api.get<AgentHealth>(
        `${orgApiBase}/agents/${agentId}/healthz`,
        { schema: AgentHealthSchema }
      );
      return response.data;
    },
    enabled,
    refetchInterval: refetchIntervalMs,
    retry: false,
  });

  return {
    health: query.data ?? (query.isError ? { status: "error" as const } : null),
    isLoadingHealth: query.isPending,
  };
}
