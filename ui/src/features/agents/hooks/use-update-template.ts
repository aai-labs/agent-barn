"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { AgentTemplateRead, AgentTemplateReadSchema } from "../schemas";
import { templatesKey } from "../utils";

export type UpdateTemplateData = {
  // template_name is immutable — new versions inherit the v1 name.
  slug: string;
  soulMd?: string;
  identityMd?: string;
  userMd?: string;
  toolsMd?: string;
  agentsMd?: string;
  bootMd?: string;
  bootstrapMd?: string;
  heartbeatMd?: string;
};

export function useUpdateTemplate() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ slug, ...data }: UpdateTemplateData) => {
      const response = await api.patch<AgentTemplateRead>(
        `/api/v1/templates/${slug}`,
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
