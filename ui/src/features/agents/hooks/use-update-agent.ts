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
  // Re-pin the agent to a different template version (both required together).
  templateSlug?: string;
  templateVersion?: number;
  slackChannelIds?: string[];
  slackDmUserIds?: string[];
  slackGroupPolicy?: "open" | "allowlist";
  slackDmPolicy?: "off" | "open" | "allowlist";
  teamsAppId?: string;
  teamsAppPassword?: string;
  teamsTenantId?: string;
  skillIds?: string[];
  removedSkillIds?: string[];
  // Integration credentials: upsert (add/replace) + explicit removal.
  secrets?: Array<{ provider: string; content: Record<string, string | string[]> }>;
  removedSecretProviders?: string[];
  approvalMode?: "manual" | "auto" | "off";
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
