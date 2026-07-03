"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { Agent, AgentSchema } from "../schemas";
import { agentsKey } from "../utils";

export type CreateAgentData = {
  name: string;
  platform: "slack" | "teams";
  agentType?: "openclaw" | "hermes";
  // Slack (required when platform=slack)
  slackBotToken?: string;
  slackAppToken?: string;
  slackGroupPolicy?: "open" | "allowlist";
  slackDmPolicy?: "off" | "open" | "allowlist";
  // Teams (required when platform=teams)
  teamsAppId?: string;
  teamsAppPassword?: string;
  teamsTenantId?: string;
  // Template reference — pins to templateVersion if given, else latest.
  templateSlug: string;
  templateVersion?: number;
  model?: string;
  // Skills to assign on creation
  skillIds?: string[];
  // Integration credentials (provider + provider-specific content; name is server-stamped)
  secrets?: Array<{ provider: string; content: Record<string, string> }>;
  approvalMode?: "manual" | "auto" | "off";
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
