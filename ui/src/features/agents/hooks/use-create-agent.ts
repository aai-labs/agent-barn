"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import { Agent, AgentSchema } from "../schemas";
import { agentsKey } from "../utils";

export type CreateAgentData = {
  name: string;
  agentType?: "openclaw" | "hermes";
  // Template reference — pins to templateVersion if given, else latest.
  templateKey: string;
  templateVersion?: number;
  model?: string;
  // Skills to assign on creation
  skillIds?: string[];
  // Integration credentials (provider + provider-specific content; name is server-stamped)
  secrets?: Array<{ provider: string; content: Record<string, string | string[] | boolean> }>;
  // Shared credentials to attach (by ID)
  sharedCredentials?: Array<{ sharedCredentialId: string }>;
  approvalMode?: "manual" | "auto" | "off";
};

export function useCreateAgent() {
  const queryClient = useQueryClient();
  const orgApiBase = useOrganizationApiBase();

  return useMutation({
    mutationFn: async (data: CreateAgentData) => {
      const response = await api.post<Agent>(`${orgApiBase}/agents`, data, {
        schema: AgentSchema,
      });
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: agentsKey.all });
    },
  });
}
