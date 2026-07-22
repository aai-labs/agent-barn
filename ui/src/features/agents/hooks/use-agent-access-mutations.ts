"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { AgentAccessMemberRead, AgentAccessMemberReadSchema } from "../schemas";
import { agentsKey } from "../utils";

export function useAgentAccessMutations(agentId: string) {
  const queryClient = useQueryClient();
  const base = `/api/v1/agents/${agentId}/access`;

  const invalidateSharing = () => {
    void queryClient.invalidateQueries({ queryKey: agentsKey.access(agentId) });
    void queryClient.invalidateQueries({ queryKey: agentsKey.detail(agentId) });
    void queryClient.invalidateQueries({ queryKey: agentsKey.lists() });
  };

  const grantAccess = useMutation({
    mutationFn: async (vars: { userId: string; accessRoleId: string }) => {
      const response = await api.post<AgentAccessMemberRead>(
        base,
        { userId: vars.userId, accessRoleId: vars.accessRoleId },
        { schema: AgentAccessMemberReadSchema },
      );
      return response.data;
    },
    onSuccess: invalidateSharing,
  });

  const changeAccessRole = useMutation({
    mutationFn: async (vars: { userId: string; accessRoleId: string }) => {
      const response = await api.patch<AgentAccessMemberRead>(
        `${base}/${vars.userId}`,
        { accessRoleId: vars.accessRoleId },
        { schema: AgentAccessMemberReadSchema },
      );
      return response.data;
    },
    onSuccess: invalidateSharing,
  });

  const revokeAccess = useMutation({
    mutationFn: async (userId: string) => {
      await api.delete(`${base}/${userId}`);
    },
    onSuccess: invalidateSharing,
  });

  return { grantAccess, changeAccessRole, revokeAccess };
}
