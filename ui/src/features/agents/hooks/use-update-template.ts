"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import { AgentTemplateRead, AgentTemplateReadSchema } from "../schemas";
import { templatesKey } from "../utils";

export type UpdateTemplateData = {
  // template_name is immutable — new versions inherit the v1 name.
  slug: string;
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
  // "At least one of" requirement groups (e.g. GitHub OR Bitbucket). Omitting
  // this field inherits the prior version's groups.
  requiredSkillGroups?: { groupKey: string; skillIds: string[] }[];
};

export function useUpdateTemplate() {
  const queryClient = useQueryClient();
  const orgApiBase = useOrganizationApiBase();

  return useMutation({
    mutationFn: async ({ slug, ...data }: UpdateTemplateData) => {
      const response = await api.patch<AgentTemplateRead>(
        `${orgApiBase}/templates/${slug}`,
        data,
        { schema: AgentTemplateReadSchema },
      );
      return response.data;
    },
    onSuccess: (data) => {
      queryClient.setQueryData(templatesKey.detail(data.templateSlug), data);
      void queryClient.invalidateQueries({ queryKey: templatesKey.lists() });
    },
  });
}
