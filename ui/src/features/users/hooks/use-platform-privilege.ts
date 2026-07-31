"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { InfiniteData } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { type PaginatedUsers, type UserRead, UserReadSchema } from "../schemas";
import { usersKey } from "../utils";

type PlatformPrivilegeChange = {
  userId: string;
  isPlatformAdmin: boolean;
  reason: string;
};

export function usePlatformPrivilege() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({
      userId,
      isPlatformAdmin,
      reason,
    }: PlatformPrivilegeChange) => {
      const response = await api.patch(
        `/api/v1/platform/users/${userId}/platform-privilege`,
        { isPlatformAdmin, reason },
        { schema: UserReadSchema },
      );
      return response.data;
    },
    onSuccess: (data, variables) => {
      // Write the fresh user straight into every cached list page and the detail
      // query, so the grid and detail views flip immediately — don't wait on a
      // background refetch to land before the button reflects the new state.
      queryClient.setQueryData(
        usersKey.detail(variables.userId),
        (previous: UserRead | undefined) =>
          previous ? { ...previous, ...data } : previous,
      );

      queryClient.setQueriesData<InfiniteData<PaginatedUsers>>(
        { queryKey: usersKey.lists() },
        (previous) => {
          if (!previous) return previous;
          return {
            ...previous,
            pages: previous.pages.map((page) => ({
              ...page,
              items: page.items.map((item) =>
                item.id === variables.userId ? { ...item, ...data } : item,
              ),
            })),
          };
        },
      );

      void queryClient.invalidateQueries({ queryKey: usersKey.lists() });
      void queryClient.invalidateQueries({
        queryKey: usersKey.detail(variables.userId),
      });
    },
  });
}
