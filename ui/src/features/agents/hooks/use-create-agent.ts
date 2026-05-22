"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { Agent, AgentSchema } from "../schemas";
import { agentsKey } from "../utils";

export type CreateAgentData = {
  name: string;
  slackBotToken: string;
  slackAppToken: string;
  soulMd: string;
  identityMd: string;
  userMd?: string;
  toolsMd?: string;
  agentsMd?: string;
  bootMd?: string;
  bootstrapMd?: string;
  heartbeatMd?: string;
  model?: string;
  slackGroupPolicy?: "open" | "allowlist";
  slackDmPolicy?: "off" | "open" | "allowlist" | "pairing";
};

export function useCreateAgent() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (data: CreateAgentData) => {
      const response = await api.post<Agent>("/api/v1/agents", data, {
        schema: AgentSchema,
      });
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: agentsKey.all });
    },
  });
}
