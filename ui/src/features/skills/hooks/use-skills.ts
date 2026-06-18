"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { PaginatedSkillsSchema, type PaginatedSkills, type SkillSource } from "../schemas";
import { SKILLS_PAGE_SIZE, skillsKey } from "../utils";

export type SkillsFilters = {
  search?: string;
  source?: SkillSource;
  page?: number;
  pageSize?: number;
};

export function useSkills(filters: SkillsFilters = {}) {
  const { search, source, page = 1, pageSize = SKILLS_PAGE_SIZE } = filters;

  const query = useQuery({
    queryKey: skillsKey.list({ filters }),
    queryFn: async () => {
      const params = new URLSearchParams();
      params.set("page", String(page));
      params.set("page_size", String(pageSize));
      if (search) params.set("search", search);
      if (source) params.set("source", source);
      const response = await api.get<PaginatedSkills>(
        `/api/v1/skills?${params.toString()}`,
        { schema: PaginatedSkillsSchema },
      );
      return response.data;
    },
  });

  return {
    skills: query.data?.items ?? [],
    total: query.data?.total ?? 0,
    page: query.data?.page ?? page,
    pageSize: query.data?.pageSize ?? pageSize,
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}