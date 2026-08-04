"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import {
  PlatformTemplateReadSchema,
  type PlatformTemplate,
} from "../schemas";
import { platformTemplatePublishedKey } from "../utils";

export function usePlatformTemplate(templateKey: string | null, enabled = true) {
  const query = useQuery({
    queryKey: platformTemplatePublishedKey.detail(templateKey ?? ""),
    queryFn: async () => {
      const response = await api.get<PlatformTemplate>(
        `/api/v1/platform/templates/${templateKey}`,
        { schema: PlatformTemplateReadSchema },
      );
      return response.data;
    },
    enabled: Boolean(templateKey) && enabled,
  });

  return {
    template: query.data,
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
  };
}
