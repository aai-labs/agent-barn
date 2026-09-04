"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import {
  PlatformTemplateAdminSummariesSchema,
  type PlatformTemplateAdminSummary,
} from "../schemas";
import { useTemplatesBasePath, type TemplateScopeRef } from "../scope";
import { templateLineagesKey } from "../utils";

export function useTemplateLineages(scope: TemplateScopeRef, enabled = true) {
  const basePath = useTemplatesBasePath(scope);
  const path = scope.kind === "platform" ? basePath : `${basePath}/lineages`;
  const query = useQuery({
    queryKey: templateLineagesKey(scope),
    queryFn: async () => {
      const response = await api.get<PlatformTemplateAdminSummary[]>(path, {
        schema: PlatformTemplateAdminSummariesSchema,
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
