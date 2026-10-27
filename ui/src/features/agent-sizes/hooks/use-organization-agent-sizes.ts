"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";
import { PlatformOrganizationSchema, type PlatformOrganization } from "@/features/organizations/schemas";
import { platformOrganizationsKey } from "@/features/organizations/utils";
import { api } from "@/shared/api";

import { OrganizationAgentSizesSchema, type OrganizationAgentSizes } from "../schemas";
import { agentSizesKey } from "../utils";

/** The sizes the active Organization's Agents may be put on, the default first. Any member may read it. */
export function useOrganizationAgentSizes() {
  const { selectedOrganization } = useOrganizationContext();
  const organizationId = selectedOrganization?.id ?? "";
  const query = useQuery({
    queryKey: agentSizesKey.organization(organizationId),
    queryFn: async () =>
      (
        await api.get<OrganizationAgentSizes>(`/api/v1/organizations/${organizationId}/agent-sizes`, {
          schema: OrganizationAgentSizesSchema,
        })
      ).data,
    // Changes only when a Platform Administrator changes the catalog or the allowed set.
    staleTime: 60_000,
    enabled: !!organizationId,
  });
  return {
    agentSizes: query.data ?? null,
    isLoadingAgentSizes: query.isPending,
    agentSizesError: query.error,
  };
}

/**
 * Set the sizes an Organization may choose beyond the default; empty means it cannot choose.
 * Platform Administrators only. Failures are left to the caller to show inline.
 */
export function useSetOrganizationAgentSizes(organizationId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (agentSizeIds: string[]) =>
      (
        await api.put<PlatformOrganization>(
          `/api/v1/platform/organizations/${organizationId}/agent-sizes`,
          { agentSizeIds },
          { schema: PlatformOrganizationSchema },
        )
      ).data,
    onSuccess: (organization) => {
      queryClient.setQueryData(platformOrganizationsKey.detail(organizationId), organization);
      void queryClient.invalidateQueries({ queryKey: platformOrganizationsKey.lists() });
      void queryClient.invalidateQueries({ queryKey: agentSizesKey.organization(organizationId) });
    },
  });
}
