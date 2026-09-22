"use client";

import { useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

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

/**
 * Reads the Agent now rather than from cache. The detail query neither polls nor
 * refetches on focus, so anything sending the Agent's own state back to the server
 * must build that request from a current read or be rejected as stale.
 */
export function useFetchAgent() {
  const queryClient = useQueryClient();
  const orgApiBase = useOrganizationApiBase();

  return useCallback(
    async (agentId: string) => {
      const response = await api.get<Agent>(`${orgApiBase}/agents/${agentId}`, {
        schema: AgentSchema,
      });
      queryClient.setQueryData(agentsKey.detail(agentId), response.data);
      return response.data;
    },
    [orgApiBase, queryClient],
  );
}
