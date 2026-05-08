"use client";

import { useInfiniteQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import {
  PaginatedOrganizations,
  PaginatedOrganizationsSchema,
} from "../schemas";
import { ORGANIZATIONS_PAGE_SIZE, organizationsKey } from "../utils";

type UseInfiniteOrganizationsOptions = {
  search?: string;
  pageSize?: number;
};

export function useInfiniteOrganizations(
  options: UseInfiniteOrganizationsOptions = {},
) {
  const search = options.search?.trim() ?? "";
  const pageSize = options.pageSize ?? ORGANIZATIONS_PAGE_SIZE;

  const query = useInfiniteQuery({
    queryKey: organizationsKey.list({
      scope: { mode: "infinite" },
      filters: { search, pageSize },
    }),
    queryFn: async ({ pageParam = 1 }) => {
      const params = new URLSearchParams();
      params.set("page", String(pageParam));
      params.set("page_size", String(pageSize));

      if (search) {
        params.set("search", search);
      }

      const response = await api.get<PaginatedOrganizations>(
        `/api/v1/organizations?${params.toString()}`,
        { schema: PaginatedOrganizationsSchema },
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
    organizations: query.data?.pages.flatMap((page) => page.items) ?? [],
    total: query.data?.pages[0]?.total ?? 0,
    hasNextPage: query.hasNextPage,
    fetchNextPage: query.fetchNextPage,
    isFetchingNextPage: query.isFetchingNextPage,
    isLoading: query.isPending,
    isFetching: query.isFetching,
    error: query.error,
    refetch: query.refetch,
  };
}
