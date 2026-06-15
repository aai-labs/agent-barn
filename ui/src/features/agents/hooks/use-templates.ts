"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import {
  PaginatedTemplates,
  PaginatedTemplatesSchema,
  TemplateSource,
} from "../schemas";
import { TEMPLATES_PAGE_SIZE, templatesKey } from "../utils";

export type TemplatesFilters = {
  search?: string;
  source?: TemplateSource;
};

export function useTemplates(filters: TemplatesFilters = {}) {
  const query = useQuery({
    queryKey: templatesKey.list({ filters }),
    queryFn: async () => {
      const params = new URLSearchParams();
      params.set("page", "1");
      params.set("page_size", String(TEMPLATES_PAGE_SIZE));
      if (filters.search) params.set("search", filters.search);
      if (filters.source) params.set("source", filters.source);
      const response = await api.get<PaginatedTemplates>(
        `/api/v1/templates?${params.toString()}`,
        { schema: PaginatedTemplatesSchema },
      );
      return response.data;
    },
  });

  return {
    templates: query.data?.items ?? [],
    total: query.data?.total ?? 0,
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}
