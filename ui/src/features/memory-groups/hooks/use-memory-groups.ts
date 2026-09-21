"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import { MemoryGroup, MemoryGroupsSchema } from "../schemas";
import { memoryGroupsKey } from "../utils";

export function useMemoryGroups() {
  const orgApiBase = useOrganizationApiBase();
  const query = useQuery({
    queryKey: memoryGroupsKey.list(),
    queryFn: async () => {
      const response = await api.get<MemoryGroup[]>(`${orgApiBase}/memory-groups`, {
        schema: MemoryGroupsSchema,
      });
      return response.data;
    },
  });

  return {
    groups: query.data ?? [],
    isLoading: query.isPending,
    error: query.error,
  };
}
