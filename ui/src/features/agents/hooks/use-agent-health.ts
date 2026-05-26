"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { AgentHealth, AgentHealthSchema } from "../schemas";
import { agentsKey } from "../utils";

export function useAgentHealth(agentId: string, enabled: boolean) {
  const query = useQuery({
    queryKey: agentsKey.health(agentId),
    queryFn: async () => {
      const response = await api.get<AgentHealth>(
        `/api/v1/agents/${agentId}/healthz`,
        { schema: AgentHealthSchema }
      );
      return response.data;
    },
    enabled,
    refetchInterval: 60_000,
    retry: false,
  });

  return {
    health: query.data ?? (query.isError ? { status: "error" as const } : null),
    isLoadingHealth: query.isPending,
  };
}
