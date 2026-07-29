"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import { Agent, AgentSchema } from "../schemas";
import { agentsKey } from "../utils";

export function useAgent(agentId: string) {
  const orgApiBase = useOrganizationApiBase();
  const query = useQuery({
    queryKey: agentsKey.detail(agentId),
    queryFn: async () => {
      const response = await api.get<Agent>(`${orgApiBase}/agents/${agentId}`, {
        schema: AgentSchema,
      });
      return response.data;
    },
    enabled: !!agentId,
  });

  return {
    agent: query.data,
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}
