"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { Agent, AgentSchema } from "../schemas";
import { agentsKey } from "../utils";

export type UpdateAgentData = {
  agentId: string;
  name?: string;
  model?: string;
  slackBotToken?: string;
  slackAppToken?: string;
  soulMd?: string;
  identityMd?: string;
  userMd?: string;
  toolsMd?: string;
  agentsMd?: string;
  bootMd?: string;
  bootstrapMd?: string;
  heartbeatMd?: string;
  slackChannelIds?: string[];
  slackDmUserIds?: string[];
  slackGroupPolicy?: "open" | "allowlist";
  slackDmPolicy?: "off" | "open" | "allowlist";
  teamsAppId?: string;
  teamsAppPassword?: string;
  teamsTenantId?: string;
  // Integration credentials: upsert (add/replace) + explicit removal.
  secrets?: Array<{ provider: string; content: Record<string, string> }>;
  removedSecretProviders?: string[];
};

export function useUpdateAgent() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ agentId, ...data }: UpdateAgentData) => {
      const response = await api.patch<Agent>(`/api/v1/agents/${agentId}`, data, {
        schema: AgentSchema,
      });
      return response.data;
    },
    onSuccess: (data) => {
      queryClient.setQueryData(agentsKey.detail(data.id), data);
      void queryClient.invalidateQueries({ queryKey: agentsKey.lists() });
    },
  });
}
