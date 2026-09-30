"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";

import { MemoryGroup, MemoryGroupsSchema } from "../schemas";
import { memoryGroupsKey } from "../utils";

/** `enabled` gates the fetch: the endpoint requires memory_group.manage, so a
 *  non-manager view (e.g. the agent Memory tab) passes `enabled: false` to avoid a
 *  403 (and its retries). The key is org-scoped so groups never leak across orgs. */
export function useMemoryGroups(options?: { enabled?: boolean }) {
  const orgApiBase = useOrganizationApiBase();
  const { selectedOrganization } = useOrganizationContext();
  const query = useQuery({
    queryKey: memoryGroupsKey.list({ org: selectedOrganization?.id ?? "" }),
    queryFn: async () => {
      const response = await api.get<MemoryGroup[]>(`${orgApiBase}/memory-groups`, {
        schema: MemoryGroupsSchema,
      });
      return response.data;
    },
    enabled: options?.enabled ?? true,
  });

  return {
    groups: query.data ?? [],
    isLoading: query.isPending,
    error: query.error,
  };
}
