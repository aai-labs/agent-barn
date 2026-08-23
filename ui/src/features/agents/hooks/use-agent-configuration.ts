"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import { AgentConfiguration, AgentConfigurationSchema } from "../schemas";
import { agentsKey } from "../utils";

export function useAgentConfiguration(agentId: string) {
  const orgApiBase = useOrganizationApiBase();
  const query = useQuery({
    queryKey: agentsKey.configuration(agentId),
    queryFn: async () => {
      const response = await api.get<AgentConfiguration>(
        `${orgApiBase}/agents/${agentId}/configuration`,
        { schema: AgentConfigurationSchema },
      );
      return response.data;
    },
    enabled: !!agentId,
  });

  return {
    configuration: query.data,
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}
