"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import {
  TemplateLineageSummariesSchema,
  type TemplateLineageSummary,
} from "../schemas";
import { useTemplatesBasePath, type TemplateScopeRef } from "../scope";
import { templateLineagesKey } from "../utils";

export function useTemplateLineages(scope: TemplateScopeRef, enabled = true) {
  const basePath = useTemplatesBasePath(scope);
  const path = scope.kind === "platform" ? basePath : `${basePath}/lineages`;
  const query = useQuery({
    queryKey: templateLineagesKey(scope),
    queryFn: async () => {
      const response = await api.get<TemplateLineageSummary[]>(path, {
        schema: TemplateLineageSummariesSchema,
      });
      return response.data;
    },
    enabled,
  });

  return {
    lineages: query.data ?? [],
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
  };
}
