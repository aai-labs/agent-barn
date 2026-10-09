"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { TemplateReadSchema, type TemplateRead } from "../schemas";
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
      const response = await api.get<TemplateRead[]>(
        `${basePath}/${templateKey}/versions`,
        {
          schema: TemplateReadSchema.array(),
          params: scope.kind === "organization" ? { include_platform: true } : undefined,
        },
      );
      if (scope.kind !== "organization") return response.data;
      // Platform and Organization sequences are independently numbered.
      return [...response.data].sort((a, b) =>
        Date.parse(b.createdAt) - Date.parse(a.createdAt) ||
        Number(b.organizationId !== null) - Number(a.organizationId !== null) ||
        b.version - a.version,
      );
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
