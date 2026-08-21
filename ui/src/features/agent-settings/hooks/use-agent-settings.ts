"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";

import { AgentSettingsSchema, type AgentSettings } from "../schemas";
import { agentSettingsKey } from "../utils";

export function useAgentSettings() {
  const orgApiBase = useOrganizationApiBase();
  const { selectedOrganization } = useOrganizationContext();
  const organizationId = selectedOrganization?.id ?? "";

  const query = useQuery({
    queryKey: agentSettingsKey.detail(organizationId),
    queryFn: async () => {
      const response = await api.get<AgentSettings>(`${orgApiBase}/agent-settings`, {
        schema: AgentSettingsSchema,
      });
      return response.data;
    },
    enabled: Boolean(organizationId),
  });

  return {
    settings: query.data,
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}
