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
  page?: number;
  pageSize?: number;
};

export function useTemplates(filters: TemplatesFilters = {}) {
  const { search, source, page = 1, pageSize = TEMPLATES_PAGE_SIZE } = filters;

  const query = useQuery({
    queryKey: templatesKey.list({ filters }),
    queryFn: async () => {
      const params = new URLSearchParams();
      params.set("page", String(page));
      params.set("page_size", String(pageSize));
      if (search) params.set("search", search);
      if (source) params.set("source", source);
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
    page: query.data?.page ?? page,
    pageSize: query.data?.pageSize ?? pageSize,
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}
