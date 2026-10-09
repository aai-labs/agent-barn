"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { api } from "@/shared/api";

import { AgentSchema, type Agent } from "../schemas";
import { agentsKey } from "../utils";

export function useIntegrationIsolation(agentId: string) {
  const queryClient = useQueryClient();
  const orgApiBase = useOrganizationApiBase();
  return useMutation({
    mutationFn: async (data: { provider: string; isolated: boolean; restart: boolean }) => {
      const { provider, ...body } = data;
      const response = await api.put<Agent>(
        `${orgApiBase}/agents/${agentId}/integrations/${provider}/isolation`, body,
        // Old-pod termination is bounded; new readiness is observed after provisioning.
        { schema: AgentSchema, timeout: 120_000 },
      );
      return response.data;
    },
    onSuccess: (agent) => queryClient.setQueryData(agentsKey.detail(agentId), agent),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: agentsKey.detail(agentId) });
      void queryClient.invalidateQueries({ queryKey: agentsKey.lists() });
      void queryClient.invalidateQueries({ queryKey: agentsKey.health(agentId) });
    },
  });
}
