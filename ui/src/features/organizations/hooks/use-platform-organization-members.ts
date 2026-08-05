"use client";

import { useInfiniteQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import {
  PaginatedPlatformOrganizationMembers,
  PaginatedPlatformOrganizationMembersSchema,
} from "../schemas";
import {
  PLATFORM_ORGANIZATION_MEMBERS_PAGE_SIZE,
  platformOrganizationMembersKey,
} from "../utils";

type UsePlatformOrganizationMembersOptions = {
  search?: string;
  pageSize?: number;
};

export function usePlatformOrganizationMembers(
  organizationId: string,
  options: UsePlatformOrganizationMembersOptions = {},
) {
  const search = options.search?.trim() ?? "";
  const pageSize = options.pageSize ?? PLATFORM_ORGANIZATION_MEMBERS_PAGE_SIZE;

  const query = useInfiniteQuery({
    queryKey: platformOrganizationMembersKey.list({
      scope: { organizationId },
      filters: { search, pageSize },
    }),
    queryFn: async ({ pageParam = 1 }) => {
      const params = new URLSearchParams();
      params.set("page", String(pageParam));
      params.set("page_size", String(pageSize));

      if (search) {
        params.set("search", search);
      }

      const response = await api.get<PaginatedPlatformOrganizationMembers>(
        `/api/v1/platform/organizations/${organizationId}/members?${params.toString()}`,
        { schema: PaginatedPlatformOrganizationMembersSchema },
      );
      return response.data;
    },
    initialPageParam: 1,
    getNextPageParam: (lastPage) => {
      const nextPage = lastPage.page + 1;
      const totalPages = Math.ceil(lastPage.total / lastPage.pageSize);
      return nextPage <= totalPages ? nextPage : undefined;
    },
    enabled: !!organizationId,
  });

  return {
    members: query.data?.pages.flatMap((page) => page.items) ?? [],
    total: query.data?.pages[0]?.total ?? 0,
    hasNextPage: query.hasNextPage,
    fetchNextPage: query.fetchNextPage,
    isFetchingNextPage: query.isFetchingNextPage,
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}
