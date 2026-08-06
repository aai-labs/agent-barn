"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import {
  PlatformTemplateAdminSummariesSchema,
  type PlatformTemplateAdminSummary,
} from "../schemas";
import { platformTemplatesKey } from "../utils";

export function usePlatformTemplateLineages(enabled = true) {
  const query = useQuery({
    queryKey: platformTemplatesKey.lists(),
    queryFn: async () => {
      const response = await api.get<PlatformTemplateAdminSummary[]>(
        "/api/v1/platform/templates",
        { schema: PlatformTemplateAdminSummariesSchema },
      );
      return response.data;
    },
    enabled,
  });

  return {
    lineages: query.data ?? [],
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}
