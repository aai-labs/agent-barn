"use client";

import { useQuery } from "@tanstack/react-query";
import { z } from "zod";

import { api } from "@/shared/api";

import { AgentAccessRoleRead, AgentAccessRoleReadSchema } from "../schemas";
import { agentsKey } from "../utils";

export function useAgentShareRoles(enabled = true) {
  const query = useQuery({
    queryKey: agentsKey.shareRoles(),
    queryFn: async () => {
      const response = await api.get<AgentAccessRoleRead[]>(
        "/api/v1/agents/share-roles",
        { schema: z.array(AgentAccessRoleReadSchema) },
      );
      return response.data;
    },
    enabled,
    staleTime: 60_000,
  });

  return {
    roles: query.data ?? [],
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}
