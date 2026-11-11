"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { customApiKey } from "@/features/custom-api/hooks/use-custom-api";
import type { CustomApiBatch } from "@/features/custom-api/schemas";
import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import { Agent, AgentSchema } from "../schemas";
import { agentsKey } from "../utils";

export type UpdateAgentData = {
  agentId: string;
  name?: string;
  // null clears an explicit model, returning the Agent to its organization's default.
  model?: string | null;
  // Re-pin the agent to a different template version (both required together).
  templateKey?: string;
  templateVersion?: number;
  skillIds?: string[];
  removedSkillIds?: string[];
  // Explicit skill version pins for newly added and re-pinned skills.
  skillVersions?: Array<{ skillId: string; version: number }>;
  // Integration credentials: upsert (add/replace) + explicit removal.
  secrets?: Array<{ provider: string; content: Record<string, string | string[] | boolean> }>;
  // Shared credentials to attach (by ID)
  sharedCredentials?: Array<{ sharedCredentialId: string }>;
  removedSecretProviders?: string[];
  restart?: boolean;
  policies?: Array<{ provider: string; isolated: boolean }>;
  customApi?: Omit<CustomApiBatch, "restart">;
  approvalMode?: "manual" | "auto" | "off";
  verboseMode?: boolean;
  // null returns the Agent to the platform default.
  maxTurns?: number | null;
};

export function useUpdateAgent() {
  const queryClient = useQueryClient();
  const orgApiBase = useOrganizationApiBase();

  return useMutation({
    mutationFn: async ({ agentId, ...data }: UpdateAgentData) => {
      const response = await api.patch<Agent>(`${orgApiBase}/agents/${agentId}`, data, {
        schema: AgentSchema,
        ...(data.restart ? { timeout: 120_000 } : {}),
      });
      return response.data;
    },
    onSuccess: (data) => {
      queryClient.setQueryData(agentsKey.detail(data.id), data);
      void queryClient.invalidateQueries({ queryKey: agentsKey.lists() });
    },
    onSettled: async (_data, _error, { agentId, restart, customApi, policies }) => {
      if (restart || customApi || policies) await Promise.all([
        queryClient.invalidateQueries({ queryKey: agentsKey.detail(agentId) }),
        queryClient.invalidateQueries({ queryKey: agentsKey.lists() }),
        queryClient.invalidateQueries({ queryKey: agentsKey.health(agentId) }),
        queryClient.invalidateQueries({ queryKey: customApiKey.all }),
      ]);
    },
  });
}
