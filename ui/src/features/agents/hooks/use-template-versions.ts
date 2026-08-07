"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import { AgentTemplateRead, TemplateVersionsSchema } from "../schemas";
import { templatesKey } from "../utils";

export function useTemplateVersions(templateKey: string | null | undefined) {
  const orgApiBase = useOrganizationApiBase();
  const query = useQuery({
    queryKey: [...templatesKey.detail(templateKey ?? ""), "versions"],
    queryFn: async () => {
      const response = await api.get<AgentTemplateRead[]>(
        `${orgApiBase}/templates/${templateKey}/versions`,
        { schema: TemplateVersionsSchema },
      );
      return response.data;
    },
    enabled: !!templateKey,
  });

  return {
    versions: query.data ?? [],
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}
