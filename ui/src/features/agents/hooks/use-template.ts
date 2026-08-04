"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import { AgentTemplateRead, AgentTemplateReadSchema } from "../schemas";
import { templatesKey } from "../utils";

export function useTemplate(templateKey: string) {
  const orgApiBase = useOrganizationApiBase();
  const query = useQuery({
    queryKey: templatesKey.detail(templateKey),
    queryFn: async () => {
      const response = await api.get<AgentTemplateRead>(
        `${orgApiBase}/templates/${templateKey}`,
        { schema: AgentTemplateReadSchema },
      );
      return response.data;
    },
    enabled: !!templateKey,
  });

  return {
    template: query.data,
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}
