"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import {
  Agent,
  AgentOverrideDraft,
  AgentOverrideDraftSchema,
  AgentOverrideVersion,
  AgentOverrideVersionSchema,
  AgentSchema,
} from "../schemas";
import { agentsKey } from "../utils";

function invalidateAgentConfiguration(queryClient: ReturnType<typeof useQueryClient>, agentId: string) {
  void queryClient.invalidateQueries({ queryKey: agentsKey.configuration(agentId) });
  void queryClient.invalidateQueries({ queryKey: agentsKey.detail(agentId) });
  void queryClient.invalidateQueries({ queryKey: agentsKey.lists() });
}

export function useStartAgentOverrideDraft() {
  const queryClient = useQueryClient();
  const orgApiBase = useOrganizationApiBase();

  return useMutation({
    mutationFn: async (agentId: string) => {
      const response = await api.post<AgentOverrideDraft>(
        `${orgApiBase}/agents/${agentId}/configuration/draft`,
        undefined,
        { schema: AgentOverrideDraftSchema },
      );
      return response.data;
    },
    onSuccess: (data) => invalidateAgentConfiguration(queryClient, data.agentId),
  });
}

export type UpdateAgentOverrideDraftData = {
  agentId: string;
  expectedUpdatedAt: string;
  description?: string | null;
  soulMd?: string;
  identityMd?: string;
  userMd?: string;
  toolsMd?: string;
  agentsMd?: string;
  bootMd?: string;
  bootstrapMd?: string;
  heartbeatMd?: string;
  templateName?: string;
  requiredSkillIds?: string[];
  requiredSkillGroups?: { groupKey: string; skillIds: string[] }[];
};

export function useUpdateAgentOverrideDraft() {
  const queryClient = useQueryClient();
  const orgApiBase = useOrganizationApiBase();

  return useMutation({
    mutationFn: async ({ agentId, ...data }: UpdateAgentOverrideDraftData) => {
      const response = await api.patch<AgentOverrideDraft>(
        `${orgApiBase}/agents/${agentId}/configuration/draft`,
        data,
        { schema: AgentOverrideDraftSchema },
      );
      return response.data;
    },
    onSuccess: (data) => invalidateAgentConfiguration(queryClient, data.agentId),
  });
}

export function usePublishAgentOverride() {
  const queryClient = useQueryClient();
  const orgApiBase = useOrganizationApiBase();

  return useMutation({
    mutationFn: async ({ agentId, expectedUpdatedAt }: { agentId: string; expectedUpdatedAt: string }) => {
      const response = await api.post<AgentOverrideVersion>(
        `${orgApiBase}/agents/${agentId}/configuration/draft/publish`,
        { expectedUpdatedAt },
        { schema: AgentOverrideVersionSchema },
      );
      return response.data;
    },
    onSuccess: (data) => invalidateAgentConfiguration(queryClient, data.agentId),
  });
}

export type SelectAgentTemplateData = {
  agentId: string;
  selectionType: "platform" | "organization" | "override";
  templateKey?: string;
  templateVersion?: number;
  overrideVersion?: number;
  expectedAgentUpdatedAt: string;
};

export function useSelectAgentTemplate() {
  const queryClient = useQueryClient();
  const orgApiBase = useOrganizationApiBase();

  return useMutation({
    mutationFn: async ({ agentId, ...data }: SelectAgentTemplateData) => {
      const response = await api.post<Agent>(
        `${orgApiBase}/agents/${agentId}/configuration/select`,
        data,
        { schema: AgentSchema },
      );
      return response.data;
    },
    onSuccess: (data) => invalidateAgentConfiguration(queryClient, data.id),
  });
}
