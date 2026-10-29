"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";

import { AgentFileSyncSchema, type AgentFileSync } from "../schemas";
import { fileSyncStatusKey } from "../utils";

const STATUS_REFRESH_MS = 30_000;

export function useFileSyncQuery(agentId: string, enabled = true) {
  const orgApiBase = useOrganizationApiBase();
  const { selectedOrganization } = useOrganizationContext();
  const organizationId = selectedOrganization?.id ?? "";

  const query = useQuery({
    queryKey: fileSyncStatusKey(organizationId, agentId),
    queryFn: async () => {
      const response = await api.get<AgentFileSync>(`${orgApiBase}/agents/${agentId}/file-sync`, {
        schema: AgentFileSyncSchema,
      });
      return response.data;
    },
    enabled: enabled && Boolean(organizationId) && Boolean(agentId),
    refetchInterval: STATUS_REFRESH_MS,
  });

  return {
    fileSync: query.data,
    isLoadingFileSync: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}
