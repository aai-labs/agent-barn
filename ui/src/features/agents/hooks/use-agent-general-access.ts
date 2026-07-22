"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { AgentGeneralAccessRead, AgentGeneralAccessReadSchema } from "../schemas";
import { agentsKey } from "../utils";

export function useAgentGeneralAccess(agentId: string | undefined, enabled = true) {
  const queryClient = useQueryClient();
  const base = `/api/v1/agents/${agentId}/general-access`;

  const query = useQuery({
    queryKey: agentsKey.generalAccess(agentId ?? ""),
    queryFn: async () => {
      const response = await api.get<AgentGeneralAccessRead>(base, {
        schema: AgentGeneralAccessReadSchema,
      });
      return response.data;
    },
    enabled: enabled && !!agentId,
  });

  const invalidateSharing = () => {
    void queryClient.invalidateQueries({
      queryKey: agentsKey.generalAccess(agentId ?? ""),
    });
    void queryClient.invalidateQueries({ queryKey: agentsKey.detail(agentId ?? "") });
    void queryClient.invalidateQueries({ queryKey: agentsKey.lists() });
  };

  const setGeneralAccess = useMutation({
    mutationFn: async (accessRoleId: string) => {
      const response = await api.put<AgentGeneralAccessRead>(
        base,
        { accessRoleId },
        { schema: AgentGeneralAccessReadSchema },
      );
      return response.data;
    },
    onSuccess: invalidateSharing,
  });

  const removeGeneralAccess = useMutation({
    mutationFn: async () => {
      await api.delete(base);
    },
    onSuccess: invalidateSharing,
  });

  return {
    generalAccess: query.data,
    isLoading: query.isPending,
    error: query.error,
    setGeneralAccess,
    removeGeneralAccess,
  };
}
