"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { AgentTemplateRead, TemplateVersionsSchema } from "../schemas";
import { templatesKey } from "../utils";

export function useTemplateVersions(slug: string | null | undefined) {
  const query = useQuery({
    queryKey: [...templatesKey.detail(slug ?? ""), "versions"],
    queryFn: async () => {
      const response = await api.get<AgentTemplateRead[]>(
        `/api/v1/templates/${slug}/versions`,
        { schema: TemplateVersionsSchema },
      );
      return response.data;
    },
    enabled: !!slug,
  });

  return {
    versions: query.data ?? [],
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}
