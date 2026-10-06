"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { agentsKey } from "@/features/agents/utils";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { api } from "@/shared/api";

import { AgentMemoryStateSchema, type AgentMemoryState } from "../schemas";

export function useSetAgentMemory(agentId: string) {
  const queryClient = useQueryClient();
  const orgApiBase = useOrganizationApiBase();

  return useMutation({
    mutationFn: async (enabled: boolean) => {
      const response = await api.put<AgentMemoryState>(
        `${orgApiBase}/agents/${agentId}/memory`,
        { enabled },
        { schema: AgentMemoryStateSchema },
      );
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: agentsKey.detail(agentId) });
      void queryClient.invalidateQueries({ queryKey: agentsKey.lists() });
    },
  });
}
