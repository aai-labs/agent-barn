"use client";

import { useInfiniteQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { PaginatedUsers, PaginatedUsersSchema } from "../schemas";
import { USERS_PAGE_SIZE, usersKey } from "../utils";

type UseInfiniteUsersOptions = {
  search?: string;
  pageSize?: number;
};

export function useInfiniteUsers(options: UseInfiniteUsersOptions = {}) {
  const search = options.search?.trim() ?? "";
  const pageSize = options.pageSize ?? USERS_PAGE_SIZE;

  const query = useInfiniteQuery({
    queryKey: usersKey.list({
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

      const response = await api.get<PaginatedUsers>(
        `/api/v1/platform/users?${params.toString()}`,
        { schema: PaginatedUsersSchema },
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
    users: query.data?.pages.flatMap((page) => page.items) ?? [],
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
