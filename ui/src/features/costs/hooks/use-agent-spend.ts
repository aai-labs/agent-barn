"use client";

import { useQuery } from "@tanstack/react-query";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { api } from "@/shared/api";

import { AgentSpendListSchema, type AgentSpend } from "../schemas";
import { costFilterParams, costKey, type CostFilters } from "../utils";

/**
 * Every agent that spent anything in the window, ranked by spend.
 *
 * Returned whole rather than paginated — an organization has tens of agents, not
 * thousands — which is why the table sorts client-side instead of refetching.
 */
export function useAgentSpend(filters: CostFilters) {
  const orgApiBase = useOrganizationApiBase();
  const query = useQuery({
    queryKey: costKey.list({ scope: { view: "agent-spend" }, filters }),
    queryFn: async () => {
      const response = await api.get<AgentSpend[]>(
        `${orgApiBase}/costs/agents?${costFilterParams(filters).toString()}`,
        { schema: AgentSpendListSchema },
      );
      return response.data;
    },
  });

  return {
    agents: query.data ?? [],
    isLoadingAgents: query.isPending,
    error: query.error,
  };
}
