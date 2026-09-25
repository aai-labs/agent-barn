"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { agentsKey } from "@/features/agents/utils";

import {
  CreateMemoryGroupData,
  MemoryGroup,
  MemoryGroupSchema,
  RenameMemoryGroupData,
  ShareMemoryItemData,
  ShareMemoryItemResult,
  ShareMemoryItemResultSchema,
} from "../schemas";
import { memoryGroupsKey } from "../utils";

export function useMemoryGroupMutations() {
  const orgApiBase = useOrganizationApiBase();
  const queryClient = useQueryClient();
  const base = `${orgApiBase}/memory-groups`;

  const invalidateGroups = () => void queryClient.invalidateQueries({ queryKey: memoryGroupsKey.all });
  // Membership lives on the agent (memory_group_id), so an assignment change also
  // stales the agents list.
  const invalidateGroupsAndAgents = () => {
    invalidateGroups();
    void queryClient.invalidateQueries({ queryKey: agentsKey.all });
  };

  const create = useMutation({
    mutationFn: async (data: CreateMemoryGroupData) => {
      const response = await api.post<MemoryGroup>(base, data, { schema: MemoryGroupSchema });
      return response.data;
    },
    onSuccess: invalidateGroups,
  });

  const rename = useMutation({
    mutationFn: async ({ id, name }: RenameMemoryGroupData) => {
      const response = await api.patch<MemoryGroup>(`${base}/${id}`, { name }, { schema: MemoryGroupSchema });
      return response.data;
    },
    onSuccess: invalidateGroups,
  });

  const remove = useMutation({
    mutationFn: async (id: string) => {
      await api.delete(`${base}/${id}`);
    },
    // Deleting a group unassigns its members, so refresh agents too.
    onSuccess: invalidateGroupsAndAgents,
  });

  const addAgent = useMutation({
    mutationFn: async ({ groupId, agentId }: { groupId: string; agentId: string }) => {
      await api.put(`${base}/${groupId}/agents/${agentId}`);
    },
    onSuccess: invalidateGroupsAndAgents,
  });

  const removeAgent = useMutation({
    mutationFn: async ({ groupId, agentId }: { groupId: string; agentId: string }) => {
      await api.delete(`${base}/${groupId}/agents/${agentId}`);
    },
    onSuccess: invalidateGroupsAndAgents,
  });

  // Copies one memory item from the source group's pool into other groups' pools.
  // It writes into the *destination* pools, so nothing the caller is currently
  // viewing changes — there is nothing to invalidate here.
  const shareItem = useMutation({
    mutationFn: async ({ sourceGroupId, memoryId, targetGroupIds }: ShareMemoryItemData) => {
      const response = await api.post<ShareMemoryItemResult>(
        `${base}/${sourceGroupId}/shared-items`,
        { memoryId, targetGroupIds },
        { schema: ShareMemoryItemResultSchema },
      );
      return response.data;
    },
  });

  return { create, rename, remove, addAgent, removeAgent, shareItem };
}
