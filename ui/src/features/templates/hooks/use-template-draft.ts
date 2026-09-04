"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { PlatformTemplateDraftReadSchema, type PlatformTemplateDraft } from "../schemas";
import { useTemplatesBasePath, type TemplateScopeRef } from "../scope";
import { templateDraftKey } from "../utils";

export function useTemplateDraft(
  scope: TemplateScopeRef,
  templateKey: string | null,
  enabled = true,
) {
  const basePath = useTemplatesBasePath(scope);
  const query = useQuery({
    queryKey: templateDraftKey(templateKey ?? "", scope),
    queryFn: async () => {
      const response = await api.get<PlatformTemplateDraft>(
        `${basePath}/${templateKey}/draft`,
        { schema: PlatformTemplateDraftReadSchema },
      );
      return response.data;
    },
    enabled: Boolean(templateKey) && enabled,
  });

  return {
    draft: query.data,
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
  };
}
