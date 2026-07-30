"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import {
  AgentAccessSettingsRead,
  AgentAccessSettingsReadSchema,
  AgentAccessSettingsUpdate,
} from "../schemas";
import { agentsKey } from "../utils";

export function useAgentShareSettings(agentId: string | undefined, enabled = true) {
  const queryClient = useQueryClient();
  const orgApiBase = useOrganizationApiBase();
  const url = `${orgApiBase}/agents/${agentId}/share`;

  const query = useQuery({
    queryKey: agentsKey.shareSettings(agentId ?? ""),
    queryFn: async () => {
      const response = await api.get<AgentAccessSettingsRead>(url, {
        schema: AgentAccessSettingsReadSchema,
      });
      return response.data;
    },
    enabled: enabled && !!agentId,
  });

  // One PUT call saves the full desired snapshot (General Access + all explicit
  // assignments) atomically — no per-recipient grant/change/revoke calls.
  const save = useMutation({
    mutationFn: async (data: AgentAccessSettingsUpdate) => {
      const response = await api.put<AgentAccessSettingsRead>(url, data, {
        schema: AgentAccessSettingsReadSchema,
      });
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: agentsKey.shareSettings(agentId ?? ""),
      });
      void queryClient.invalidateQueries({ queryKey: agentsKey.detail(agentId ?? "") });
      void queryClient.invalidateQueries({ queryKey: agentsKey.lists() });
    },
  });

  return {
    settings: query.data,
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
    save,
  };
}
