"use client";

import { type QueryClient, useQuery } from "@tanstack/react-query";
import { z } from "zod";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import { Agent, AgentSchema } from "../schemas";
import { agentsKey } from "../utils";

export function refreshBotsOf(queryClient: QueryClient, parentAgentId: string) {
  for (const bot of queryClient.getQueryData<Agent[]>(agentsKey.bots(parentAgentId)) ?? []) {
    void queryClient.invalidateQueries({ queryKey: agentsKey.detail(bot.id) });
  }
  void queryClient.invalidateQueries({ queryKey: agentsKey.bots(parentAgentId) });
}

export function useBots(parentAgentId: string, { enabled = true }: { enabled?: boolean } = {}) {
  const orgApiBase = useOrganizationApiBase();
  const query = useQuery({
    queryKey: agentsKey.bots(parentAgentId),
    enabled,
    queryFn: async () => {
      const response = await api.get<Agent[]>(`${orgApiBase}/agents/${parentAgentId}/bots`, {
        schema: z.array(AgentSchema),
      });
      return response.data;
    },
  });

  return { bots: query.data ?? [], isLoading: query.isPending };
}
