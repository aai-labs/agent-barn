"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import {
  PlatformTemplateReadSchema,
  type PlatformTemplate,
} from "../schemas";
import { platformTemplateVersionsKey } from "../utils";

export function usePlatformTemplateVersions(templateKey: string | null, enabled = true) {
  const query = useQuery({
    queryKey: platformTemplateVersionsKey.detail(templateKey ?? ""),
    queryFn: async () => {
      const response = await api.get<PlatformTemplate[]>(
        `/api/v1/platform/templates/${templateKey}/versions`,
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
