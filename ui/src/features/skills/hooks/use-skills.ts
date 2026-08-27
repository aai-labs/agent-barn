"use client";

import { useMemo } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { PaginatedSkillsSchema, SkillSchema, type PaginatedSkills, type Skill, type SkillSource } from "../schemas";
import { skillScopeCacheKey, useSkillsBasePath, type SkillScopeRef } from "../scope";
import { SKILLS_PAGE_SIZE, skillsKey } from "../utils";

export type SkillsFilters = {
  scope: SkillScopeRef;
  search?: string;
  source?: SkillSource;
  page?: number;
  pageSize?: number;
};

/** Skills visible from a scope: Platform lists every global Skill; Organization
 * lists Platform + its own; Agent additionally includes that Agent's private Skills.
 *
 * Platform's list endpoint is a small, curated admin catalogue with no
 * pagination/filter contract (unlike the per-tenant Organization/Agent routes) —
 * so it's fetched once and filtered client-side, trading a slightly larger single
 * payload for zero round trips per keystroke or page turn.
 *
 * Two separate `useQuery` calls (rather than one `queryFn` branching on scope)
 * so each keeps a single, cleanly inferred response type — only one is ever
 * `enabled` for a given scope, so exactly one of them ever fetches.
 */
export function useSkills(filters: SkillsFilters) {
  const { scope, search, source, page = 1, pageSize = SKILLS_PAGE_SIZE } = filters;
  const basePath = useSkillsBasePath(scope);
  const isPlatform = scope.kind === "platform";

  const platformQuery = useQuery({
    queryKey: skillsKey.list({ scope: { scope: skillScopeCacheKey(scope) } }),
    enabled: isPlatform,
    queryFn: async () => {
      const response = await api.get<Skill[]>(basePath, { schema: SkillSchema.array() });
      return response.data;
    },
  });

  const tenantQuery = useQuery({
    queryKey: skillsKey.list({ scope: { scope: skillScopeCacheKey(scope) }, filters: { search, source, page, pageSize } }),
    enabled: !isPlatform,
    queryFn: async () => {
      const params = new URLSearchParams();
      params.set("page", String(page));
      params.set("page_size", String(pageSize));
      if (search) params.set("search", search);
      if (source) params.set("source", source);
      const response = await api.get<PaginatedSkills>(`${basePath}?${params.toString()}`, {
        schema: PaginatedSkillsSchema,
      });
      return response.data;
    },
  });

  const filteredPlatformSkills = useMemo(() => {
    const all = platformQuery.data ?? [];
    const lowerSearch = search?.trim().toLowerCase();
    return all.filter(
      (skill) =>
        (!lowerSearch || skill.name.toLowerCase().includes(lowerSearch)) && (!source || skill.source === source),
    );
  }, [platformQuery.data, search, source]);

  if (isPlatform) {
    const start = (page - 1) * pageSize;
    return {
      skills: filteredPlatformSkills.slice(start, start + pageSize),
      total: filteredPlatformSkills.length,
      page,
      pageSize,
      isLoading: platformQuery.isPending,
      error: platformQuery.error,
      refetch: platformQuery.refetch,
    };
  }

  return {
    skills: tenantQuery.data?.items ?? [],
    total: tenantQuery.data?.total ?? 0,
    page: tenantQuery.data?.page ?? page,
    pageSize: tenantQuery.data?.pageSize ?? pageSize,
    isLoading: tenantQuery.isPending,
    error: tenantQuery.error,
    refetch: tenantQuery.refetch,
  };
}

/**
 * Paginated tenant Skill lists for screens that keep loading as the user
 * reaches the end. The platform catalogue still uses `useSkills` because its
 * endpoint intentionally returns the complete global list.
 */
export function useInfiniteSkills(
  filters: Omit<SkillsFilters, "page">,
) {
  const { scope, search, source, pageSize = SKILLS_PAGE_SIZE } = filters;
  const basePath = useSkillsBasePath(scope);
  const normalizedSearch = search?.trim() ?? "";

  const query = useInfiniteQuery({
    queryKey: skillsKey.list({
      scope: { scope: skillScopeCacheKey(scope), mode: "infinite" },
      filters: { search: normalizedSearch, source, pageSize },
    }),
    queryFn: async ({ pageParam = 1 }) => {
      const params = new URLSearchParams();
      params.set("page", String(pageParam));
      params.set("page_size", String(pageSize));
      if (normalizedSearch) params.set("search", normalizedSearch);
      if (source) params.set("source", source);

      const response = await api.get<PaginatedSkills>(
        `${basePath}?${params.toString()}`,
        { schema: PaginatedSkillsSchema },
      );
      return response.data;
    },
    initialPageParam: 1,
    getNextPageParam: (lastPage) => {
      const nextPage = lastPage.page + 1;
      const totalPages = Math.ceil(lastPage.total / lastPage.pageSize);
      return nextPage <= totalPages ? nextPage : undefined;
    },
  });

  return {
    skills: query.data?.pages.flatMap((page) => page.items) ?? [],
    total: query.data?.pages[0]?.total ?? 0,
    hasNextPage: query.hasNextPage,
    fetchNextPage: query.fetchNextPage,
    isFetchingNextPage: query.isFetchingNextPage,
    isFetchingNextPageError: query.isFetchNextPageError,
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}
