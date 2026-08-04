"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import {
  PlatformTemplateDraftReadSchema,
  type PlatformTemplateDraft,
} from "../schemas";
import { platformTemplatesKey } from "../utils";

export function usePlatformTemplateDraft(slug: string | null, enabled = true) {
  const query = useQuery({
    queryKey: platformTemplatesKey.detail(slug ?? ""),
    queryFn: async () => {
      const response = await api.get<PlatformTemplateDraft>(
        `/api/v1/platform/templates/${slug}/draft`,
        { schema: PlatformTemplateDraftReadSchema },
      );
      return response.data;
    },
    enabled: Boolean(slug) && enabled,
  });

  return {
    draft: query.data,
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
  };
}
