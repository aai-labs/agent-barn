"use client";

import { useQuery } from "@tanstack/react-query";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { api } from "@/shared/api";

import { AgentCostSchema, type AgentCost } from "../schemas";
import { costKey } from "../utils";

/**
 * Spend and trend for one Agent.
 */
export function useAgentCost(
  agentId: string,
  { fromDate, toDate }: { fromDate?: string; toDate?: string },
) {
  const orgApiBase = useOrganizationApiBase();
  const query = useQuery({
    queryKey: costKey.list({
      scope: { view: "agent", agentId },
      filters: { fromDate: fromDate ?? "", toDate: toDate ?? "" },
    }),
    queryFn: async () => {
      // Only the window is sent: this route takes a StatsWindow and no filter
      const params = new URLSearchParams();
      if (fromDate) params.set("from_date", fromDate);
      if (toDate) params.set("to_date", toDate);
      const queryString = params.toString();

      const response = await api.get<AgentCost>(
        `${orgApiBase}/costs/agents/${agentId}${queryString ? `?${queryString}` : ""}`,
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
