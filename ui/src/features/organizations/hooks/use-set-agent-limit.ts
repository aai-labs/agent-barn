"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { type PlatformOrganization, PlatformOrganizationSchema } from "../schemas";
import { platformOrganizationsKey } from "../utils";

/** Sets how many agents an organization may run; null returns it to the default. */
export function useSetAgentLimit(organizationId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (agentLimit: number | null) =>
      (
        await api.put<PlatformOrganization>(
          `/api/v1/platform/organizations/${organizationId}/agent-limit`,
          { agentLimit },
          { schema: PlatformOrganizationSchema },
        )
      ).data,
    onSuccess: (organization) => {
      queryClient.setQueryData(platformOrganizationsKey.detail(organizationId), organization);
    },
  });
}
