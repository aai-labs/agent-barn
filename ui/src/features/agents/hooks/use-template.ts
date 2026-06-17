"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { AgentTemplateRead, AgentTemplateReadSchema } from "../schemas";
import { templatesKey } from "../utils";

export function useTemplate(slug: string) {
  const query = useQuery({
    queryKey: templatesKey.detail(slug),
    queryFn: async () => {
      const response = await api.get<AgentTemplateRead>(
        `/api/v1/templates/${slug}`,
        { schema: AgentTemplateReadSchema },
      );
      return response.data;
    },
    enabled: !!slug,
  });

  return {
    template: query.data,
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}
