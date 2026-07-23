"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { organizationMembersKey } from "@/features/organizations/utils";
import { OrganizationMember, OrganizationMembersSchema } from "@/features/organizations/schemas";

/**
 * Searches all Members of an Organization by name/email — including ones who already
 * have direct access to the Agent being shared. The Share dialog reconciles results
 * against the local draft itself (see share-add-member.tsx) rather than this hook
 * filtering anything out, per AF-217's "already has access" messaging requirement.
 */
export function useOrganizationMemberSearch(
  organizationId: string | undefined,
  search: string,
  enabled = true,
) {
  const query = useQuery({
    queryKey: organizationMembersKey.list({
      scope: { organizationId: organizationId ?? "" },
      filters: { search },
    }),
    queryFn: async () => {
      const response = await api.get<OrganizationMember[]>(
        `/api/v1/organizations/${organizationId}/members`,
        { schema: OrganizationMembersSchema, params: { search } },
      );
      return response.data;
    },
    enabled: enabled && !!organizationId,
  });

  return {
    members: query.data ?? [],
    isLoading: query.isPending,
    error: query.error,
  };
}
