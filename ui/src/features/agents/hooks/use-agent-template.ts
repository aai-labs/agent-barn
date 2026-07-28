"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import { AgentTemplateRead, AgentTemplateReadSchema } from "../schemas";
import { agentsKey } from "../utils";

export function useAgentTemplate(agentId: string, version: number) {
  const orgApiBase = useOrganizationApiBase();
  const query = useQuery({
    queryKey: [...agentsKey.detail(agentId), "template", version],
    queryFn: async () => {
      const response = await api.get<AgentTemplateRead>(
        `${orgApiBase}/agents/${agentId}/template/${version}`,
        { schema: AgentTemplateReadSchema },
      );
      return response.data;
    },
    enabled: !!agentId && version > 0,
  });

  return {
    template: query.data,
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}
