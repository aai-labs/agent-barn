"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import { Agent, AgentSchema } from "../schemas";
import { agentsKey } from "../utils";

export function useStartAgent() {
  const queryClient = useQueryClient();
  const orgApiBase = useOrganizationApiBase();

  return useMutation({
    mutationFn: async (agentId: string) => {
      const response = await api.post<Agent>(
        `${orgApiBase}/agents/${agentId}/start`,
        undefined,
        { schema: AgentSchema },
      );
      return response.data;
    },
    onSuccess: (data) => {
      queryClient.setQueryData(agentsKey.detail(data.id), data);
      void queryClient.invalidateQueries({ queryKey: agentsKey.lists() });
      void queryClient.invalidateQueries({ queryKey: agentsKey.health(data.id) });
    },
  });
}
