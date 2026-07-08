"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { type OrganizationMember, OrganizationMembersSchema } from "../schemas";
import { organizationMembersKey } from "../utils";

export function useOrganizationMembers(organizationId: string) {
  const query = useQuery({
    queryKey: organizationMembersKey.list({ scope: { organizationId } }),
    queryFn: async () => {
      const response = await api.get<OrganizationMember[]>(
        `/api/v1/organizations/${organizationId}/members`,
        { schema: OrganizationMembersSchema },
      );
      return response.data;
    },
    enabled: !!organizationId,
  });

  return {
    members: query.data ?? [],
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}
