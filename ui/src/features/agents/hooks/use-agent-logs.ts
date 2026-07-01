"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { AgentLogsRead, AgentLogsReadSchema } from "../schemas";
import { agentsKey } from "../utils";

export function useAgentLogs(agentId: string, enabled: boolean = true) {
  const query = useQuery({
    queryKey: agentsKey.logs(agentId),
    queryFn: async () => {
      const response = await api.get<AgentLogsRead>(
        `/api/v1/agents/${agentId}/logs`,
        { schema: AgentLogsReadSchema },
      );
      return response.data;
    },
    enabled: !!agentId && enabled,
    refetchOnWindowFocus: false,
  });

  return {
    logs: query.data ?? null,
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}
