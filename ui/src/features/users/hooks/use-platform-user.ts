"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { type PlatformUserRead, PlatformUserReadSchema } from "../schemas";
import { usersKey } from "../utils";

export function usePlatformUser(userId: string) {
  const query = useQuery({
    queryKey: usersKey.detail(userId),
    queryFn: async () => {
      const response = await api.get<PlatformUserRead>(
        `/api/v1/platform/users/${userId}`,
        { schema: PlatformUserReadSchema },
      );
      return response.data;
    },
    enabled: !!userId,
  });

  return {
    user: query.data ?? null,
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}
