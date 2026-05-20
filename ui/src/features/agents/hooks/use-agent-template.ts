"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { AgentTemplateRead, AgentTemplateReadSchema } from "../schemas";
import { agentsKey } from "../utils";

export function useAgentTemplate(agentId: string, version: number) {
  const query = useQuery({
    queryKey: [...agentsKey.detail(agentId), "template", version],
    queryFn: async () => {
      const response = await api.get<AgentTemplateRead>(
        `/api/v1/agents/${agentId}/template/${version}`,
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
