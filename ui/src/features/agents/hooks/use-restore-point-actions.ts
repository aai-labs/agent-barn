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
  // A replay rewrites the pinned configuration, so the configuration read goes too.
  void queryClient.invalidateQueries({ queryKey: agentsKey.configuration(agentId) });
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
    mutationFn: async ({
      restorePointId,
      reapplyConfiguration = false,
    }: {
      restorePointId: string;
      reapplyConfiguration?: boolean;
    }) => {
      const response = await api.post<RestorePoint>(
        `${orgApiBase}/agents/${agentId}/restore-points/${restorePointId}/restore`,
        // The server checks the recorded configuration before it starts the Job, so
        // a configuration that cannot be applied never costs the Agent its files.
        { reapplyConfiguration },
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

/** Re-applies a restore point's recorded configuration after it failed to land. */
export function useApplyRecordedConfiguration(agentId: string) {
  const queryClient = useQueryClient();
  const orgApiBase = useOrganizationApiBase();

  return useMutation({
    mutationFn: async (restorePointId: string) => {
      await api.post(
        `${orgApiBase}/agents/${agentId}/restore-points/${restorePointId}/configuration`,
        undefined,
      );
    },
    onSuccess: () => invalidateRestorePoints(queryClient, agentId),
  });
}
