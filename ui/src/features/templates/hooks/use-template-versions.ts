"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { PlatformTemplateReadSchema, type PlatformTemplate } from "../schemas";
import { useTemplatesBasePath, type TemplateScopeRef } from "../scope";
import { templateVersionsKey } from "../utils";

export function useTemplateVersions(
  scope: TemplateScopeRef,
  templateKey: string | null,
  enabled = true,
) {
  const basePath = useTemplatesBasePath(scope);
  const query = useQuery({
    queryKey: templateVersionsKey(templateKey ?? "", scope),
    queryFn: async () => {
      const response = await api.get<PlatformTemplate[]>(
        `${basePath}/${templateKey}/versions`,
        { schema: PlatformTemplateReadSchema.array() },
      );
      return response.data;
    },
    enabled: Boolean(templateKey) && enabled,
  });

  return {
    versions: query.data ?? [],
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
  };
}
