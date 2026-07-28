"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { AgentTemplateRead, AgentTemplateReadSchema } from "../schemas";
import { templatesKey } from "../utils";

export type CreateTemplateData = {
  templateName: string;
  description?: string | null;
  soulMd?: string;
  identityMd?: string;
  userMd?: string;
  toolsMd?: string;
  agentsMd?: string;
  bootMd?: string;
  bootstrapMd?: string;
  heartbeatMd?: string;
  requiredSkillIds?: string[];
  // "At least one of" requirement groups (e.g. GitHub OR Bitbucket). Not yet
  // authorable from the template editor UI, but the API supports it.
  requiredSkillGroups?: { groupKey: string; skillIds: string[] }[];
};

export function useCreateTemplate() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (data: CreateTemplateData) => {
      const response = await api.post<AgentTemplateRead>(
        "/api/v1/templates",
        data,
        { schema: AgentTemplateReadSchema },
      );
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: templatesKey.all });
    },
  });
}
