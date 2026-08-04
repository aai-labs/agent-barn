"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import {
  PlatformTemplateDraftReadSchema,
  type PlatformTemplateDraft,
} from "../schemas";
import { platformTemplatesKey } from "../utils";

export function usePlatformTemplateDraft(templateKey: string | null, enabled = true) {
  const query = useQuery({
    queryKey: platformTemplatesKey.detail(templateKey ?? ""),
    queryFn: async () => {
      const response = await api.get<PlatformTemplateDraft>(
        `/api/v1/platform/templates/${templateKey}/draft`,
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
