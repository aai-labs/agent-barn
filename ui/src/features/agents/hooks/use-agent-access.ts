"use client";

import { useQuery } from "@tanstack/react-query";
import { z } from "zod";

import { api } from "@/shared/api";

import { AgentAccessMemberRead, AgentAccessMemberReadSchema } from "../schemas";
import { agentsKey } from "../utils";

export function useAgentAccess(agentId: string | undefined, enabled = true) {
  const query = useQuery({
    queryKey: agentsKey.access(agentId ?? ""),
    queryFn: async () => {
      const response = await api.get<AgentAccessMemberRead[]>(
        `/api/v1/agents/${agentId}/access`,
        { schema: z.array(AgentAccessMemberReadSchema) },
      );
      return response.data;
    },
    enabled: enabled && !!agentId,
  });

  return {
    members: query.data ?? [],
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}
