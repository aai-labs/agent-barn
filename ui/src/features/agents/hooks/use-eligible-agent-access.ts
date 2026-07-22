"use client";

import { useQuery } from "@tanstack/react-query";
import { z } from "zod";

import { api } from "@/shared/api";

import { AgentAccessCandidateRead, AgentAccessCandidateReadSchema } from "../schemas";
import { agentsKey } from "../utils";

export function useEligibleAgentAccess(
  agentId: string | undefined,
  search: string,
  enabled = true,
) {
  const query = useQuery({
    queryKey: agentsKey.eligibleAccess(agentId ?? "", search),
    queryFn: async () => {
      const response = await api.get<AgentAccessCandidateRead[]>(
        `/api/v1/agents/${agentId}/access/eligible`,
        {
          schema: z.array(AgentAccessCandidateReadSchema),
          params: search ? { search } : undefined,
        },
      );
      return response.data;
    },
    enabled: enabled && !!agentId,
  });

  return {
    candidates: query.data ?? [],
    isLoading: query.isPending,
    error: query.error,
  };
}
