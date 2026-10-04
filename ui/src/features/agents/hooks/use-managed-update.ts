"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import { Agent, AgentSchema } from "../schemas";
import { agentsKey } from "../utils";

/**
 * The managed update (MDP-47): the server stops the Agent, captures a restore
 * point, starts the new image, and rolls back by itself if the new version
 * never becomes healthy. The 202 returns before any of that happens — the
 * Agent's status and its restore points tell the story afterwards.
 */
export function useManagedUpdate() {
  const queryClient = useQueryClient();
  const orgApiBase = useOrganizationApiBase();

  return useMutation({
    mutationFn: async (agentId: string) => {
      const response = await api.post<Agent>(
        `${orgApiBase}/agents/${agentId}/managed-update`,
        undefined,
        { schema: AgentSchema },
      );
      return response.data;
    },
    onSuccess: (data, agentId) => {
      queryClient.setQueryData(agentsKey.detail(data.id), data);
      void queryClient.invalidateQueries({ queryKey: agentsKey.lists() });
      void queryClient.invalidateQueries({ queryKey: agentsKey.restorePoints(agentId) });
      void queryClient.invalidateQueries({ queryKey: agentsKey.health(agentId) });
    },
    onError: (_error, agentId) => {
      void queryClient.invalidateQueries({ queryKey: agentsKey.detail(agentId) });
      void queryClient.invalidateQueries({ queryKey: agentsKey.lists() });
    },
  });
}
