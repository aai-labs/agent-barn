"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { customApiKey } from "@/features/custom-api/hooks/use-custom-api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { api } from "@/shared/api";

import { AgentSchema, type AgentIntegrationsApply } from "../schemas";
import { agentsKey } from "../utils";

export function useApplyIntegrations(agentId: string) {
  const queryClient = useQueryClient();
  const base = useOrganizationApiBase();

  return useMutation({
    mutationFn: async (data: AgentIntegrationsApply) => (
      await api.post(`${base}/agents/${agentId}/integrations/apply`, data, {
        schema: AgentSchema,
        timeout: 120_000,
      })
    ).data,
    onSuccess: (agent) => {
      queryClient.setQueryData(agentsKey.detail(agentId), agent);
    },
    onSettled: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: agentsKey.detail(agentId) }),
        queryClient.invalidateQueries({ queryKey: agentsKey.lists() }),
        queryClient.invalidateQueries({ queryKey: agentsKey.health(agentId) }),
        queryClient.invalidateQueries({ queryKey: customApiKey.all }),
      ]);
    },
  });
}
