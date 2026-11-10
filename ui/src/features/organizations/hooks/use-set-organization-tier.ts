"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { type PlatformOrganization, PlatformOrganizationSchema } from "../schemas";
import { platformOrganizationsKey } from "../utils";

/** Puts an organization on a tier; null takes it off any tier. */
export function useSetOrganizationTier(organizationId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (tierId: string | null) =>
      (
        await api.put<PlatformOrganization>(
          `/api/v1/platform/organizations/${organizationId}/tier`,
          { tierId },
          { schema: PlatformOrganizationSchema },
        )
      ).data,
    onSuccess: (organization) => {
      queryClient.setQueryData(platformOrganizationsKey.detail(organizationId), organization);
    },
  });
}
