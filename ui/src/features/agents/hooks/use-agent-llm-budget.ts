"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { agentSettingsKey } from "@/features/agent-settings/utils";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";

import { type AgentLlmBudget, AgentLlmBudgetSchema } from "../schemas";
import { agentsKey } from "../utils";

export function useAgentLlmBudget(agentId: string, enabled = true) {
  const orgApiBase = useOrganizationApiBase();
  const query = useQuery({
    queryKey: agentsKey.llmBudget(agentId),
    queryFn: async () => {
      const response = await api.get<AgentLlmBudget>(`${orgApiBase}/agents/${agentId}/llm-budget`, {
        schema: AgentLlmBudgetSchema,
      });
      return response.data;
    },
    // Spend is a snapshot refreshed on a schedule; refetching on every mount buys nothing.
    staleTime: 60_000,
    enabled: !!agentId && enabled,
  });

  return {
    budget: query.data,
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}

/** Set the Agent's own limit, or null to follow the organization's default. Errors
 *  are rendered inline by the caller, next to the amount that was refused. */
export function useSetAgentLlmBudget(agentId: string) {
  const orgApiBase = useOrganizationApiBase();
  const { selectedOrganization } = useOrganizationContext();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (budgetUsd: number | null) => {
      const response = await api.put<AgentLlmBudget>(
        `${orgApiBase}/agents/${agentId}/llm-budget`,
        { budgetUsd },
        { schema: AgentLlmBudgetSchema },
      );
      return response.data;
    },
    onSettled: () => {
      // Refetched on failure too: a 502 means the limit was stored and only applying
      // it failed.
      void queryClient.invalidateQueries({ queryKey: agentsKey.llmBudget(agentId) });
      // The default's "following / own limit" counts and the Agent limits overview
      // move with it.
      void queryClient.invalidateQueries({
        queryKey: agentSettingsKey.detail(selectedOrganization?.id ?? ""),
      });
      void queryClient.invalidateQueries({ queryKey: agentsKey.llmBudgets(selectedOrganization?.id ?? "") });
    },
  });
}
