"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";

import { AgentFileSyncSettingSchema, type AgentFileSyncSetting } from "../schemas";
import { agentFileSyncKey } from "../utils";

export function useSetFileSync(agentId: string) {
  const queryClient = useQueryClient();
  const orgApiBase = useOrganizationApiBase();
  const { selectedOrganization } = useOrganizationContext();
  const organizationId = selectedOrganization?.id ?? "";

  return useMutation({
    mutationFn: async (enabled: boolean) => {
      const response = await api.put<AgentFileSyncSetting>(
        `${orgApiBase}/agents/${agentId}/file-sync`,
        { enabled },
        { schema: AgentFileSyncSettingSchema },
      );
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: agentFileSyncKey(organizationId, agentId) });
    },
  });
}
