"use client";

import { useQuery } from "@tanstack/react-query";
import { z } from "zod";

import { api } from "@/shared/api";
import { AgentLlmBudgetSchema } from "@/features/agents/schemas";
import { agentsKey } from "@/features/agents/utils";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";

export const AgentLlmBudgetRowSchema = AgentLlmBudgetSchema.pick({
  limitUsd: true,
  ownLimitUsd: true,
  source: true,
  state: true,
  spendUsd: true,
}).extend({
  agentId: z.string().uuid(),
  agentName: z.string(),
});

export type AgentLlmBudgetRow = z.infer<typeof AgentLlmBudgetRowSchema>;

/** Every Agent's limit in force and where it comes from. Owners and Admins only. */
export function useAgentLlmBudgets(enabled = true) {
  const orgApiBase = useOrganizationApiBase();
  const { selectedOrganization } = useOrganizationContext();
  const organizationId = selectedOrganization?.id ?? "";

  const query = useQuery({
    queryKey: agentsKey.llmBudgets(organizationId),
    queryFn: async () => {
      const response = await api.get<AgentLlmBudgetRow[]>(`${orgApiBase}/agents/llm-budgets`, {
        schema: z.array(AgentLlmBudgetRowSchema),
      });
      return response.data;
    },
    staleTime: 60_000,
    enabled: Boolean(organizationId) && enabled,
  });

  return { agents: query.data, isLoading: query.isPending, error: query.error, refetch: query.refetch };
}
