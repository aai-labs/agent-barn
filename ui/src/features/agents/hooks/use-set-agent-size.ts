"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { api } from "@/shared/api";

import { type Agent, AgentSchema } from "../schemas";
import { agentsKey } from "../utils";

/**
 * Choose the size an Agent starts on next; null follows the platform default. Never restarts
 * the Agent: a running one reports `pendingSize` until its next start.
 */
export function useSetAgentSize() {
  const queryClient = useQueryClient();
  const orgApiBase = useOrganizationApiBase();

  return useMutation({
    mutationFn: async ({ agentId, agentSizeId }: { agentId: string; agentSizeId: string | null }) =>
      (await api.put<Agent>(`${orgApiBase}/agents/${agentId}/agent-size`, { agentSizeId }, { schema: AgentSchema }))
        .data,
    onSuccess: (agent) => {
      queryClient.setQueryData(agentsKey.detail(agent.id), agent);
      void queryClient.invalidateQueries({ queryKey: agentsKey.lists() });
    },
  });
}
