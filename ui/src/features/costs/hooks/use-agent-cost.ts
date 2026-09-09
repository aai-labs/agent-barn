"use client";

import { useQuery } from "@tanstack/react-query";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { api } from "@/shared/api";

import { AgentCostSchema, type AgentCost } from "../schemas";
import { costKey } from "../utils";

/**
 * Spend and trend for one Agent.
 */
export function useAgentCost(agentId: string, { period }: { period: string }) {
  const orgApiBase = useOrganizationApiBase();
  const query = useQuery({
    queryKey: costKey.list({
      scope: { view: "agent", agentId },
      filters: { period },
    }),
    queryFn: async () => {
      const response = await api.get<AgentCost>(
        `${orgApiBase}/costs/agents/${agentId}?period=${period}`,
        { schema: AgentCostSchema },
      );
      return response.data;
    },
  });

  return {
    agentCost: query.data ?? null,
    isLoadingAgentCost: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}
