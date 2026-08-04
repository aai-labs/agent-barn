"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import {
  PlatformTemplateReadSchema,
  type PlatformTemplate,
} from "../schemas";
import { platformTemplateVersionsKey } from "../utils";

export function usePlatformTemplateVersions(slug: string | null, enabled = true) {
  const query = useQuery({
    queryKey: platformTemplateVersionsKey.detail(slug ?? ""),
    queryFn: async () => {
      const response = await api.get<PlatformTemplate[]>(
        `/api/v1/platform/templates/${slug}/versions`,
        { schema: PlatformTemplateReadSchema.array() },
      );
      return response.data;
    },
    enabled: Boolean(slug) && enabled,
  });

  return {
    versions: query.data ?? [],
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
  };
}
