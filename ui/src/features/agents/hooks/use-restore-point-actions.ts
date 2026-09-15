"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import { RestorePoint, RestorePointSchema } from "../schemas";
import { agentsKey } from "../utils";

function invalidateRestorePoints(
  queryClient: ReturnType<typeof useQueryClient>,
  agentId: string,
) {
  void queryClient.invalidateQueries({ queryKey: agentsKey.restorePoints(agentId) });
  void queryClient.invalidateQueries({ queryKey: agentsKey.detail(agentId) });
}

export function useCreateRestorePoint(agentId: string) {
  const queryClient = useQueryClient();
  const orgApiBase = useOrganizationApiBase();

  return useMutation({
    mutationFn: async (label: string | null) => {
      const response = await api.post<RestorePoint>(
        `${orgApiBase}/agents/${agentId}/restore-points`,
        { label: label?.trim() ? label.trim() : null },
        { schema: RestorePointSchema },
      );
      return response.data;
    },
    onSuccess: () => invalidateRestorePoints(queryClient, agentId),
  });
}

export function useRestoreRestorePoint(agentId: string) {
  const queryClient = useQueryClient();
  const orgApiBase = useOrganizationApiBase();

  return useMutation({
    mutationFn: async (restorePointId: string) => {
      const response = await api.post<RestorePoint>(
        `${orgApiBase}/agents/${agentId}/restore-points/${restorePointId}/restore`,
        undefined,
        { schema: RestorePointSchema },
      );
      return response.data;
    },
    onSuccess: () => invalidateRestorePoints(queryClient, agentId),
  });
}

export function useDeleteRestorePoint(agentId: string) {
  const queryClient = useQueryClient();
  const orgApiBase = useOrganizationApiBase();

  return useMutation({
    mutationFn: async (restorePointId: string) => {
      await api.delete(`${orgApiBase}/agents/${agentId}/restore-points/${restorePointId}`);
    },
    onSuccess: () => invalidateRestorePoints(queryClient, agentId),
  });
}
