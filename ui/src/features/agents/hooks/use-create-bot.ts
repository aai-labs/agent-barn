"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { organizationsKey } from "@/features/organizations/utils";

import { Agent, AgentSchema } from "../schemas";
import { agentsKey } from "../utils";
import type { CreateAgentData } from "./use-create-agent";

export type CreateBotData = Omit<CreateAgentData, "agentType" | "fileSyncEnabled" | "agentSizeId">;

export function useCreateBot(parentAgentId: string | undefined) {
  const queryClient = useQueryClient();
  const orgApiBase = useOrganizationApiBase();

  return useMutation({
    mutationFn: async (data: CreateBotData) => {
      const response = await api.post<Agent>(`${orgApiBase}/agents/${parentAgentId}/bots`, data, {
        schema: AgentSchema,
      });
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: agentsKey.all });
      void queryClient.invalidateQueries({ queryKey: organizationsKey.all });
    },
  });
}
