"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";

import { OneDriveSyncConnectionSchema, type OneDriveSyncConnection } from "../schemas";
import { oneDriveSyncKey } from "../utils";

export function useOneDriveSyncQuery() {
  const orgApiBase = useOrganizationApiBase();
  const { selectedOrganization } = useOrganizationContext();
  const organizationId = selectedOrganization?.id ?? "";

  const query = useQuery({
    queryKey: oneDriveSyncKey.detail(organizationId),
    queryFn: async () => {
      const response = await api.get<OneDriveSyncConnection>(`${orgApiBase}/onedrive-sync/connection`, {
        schema: OneDriveSyncConnectionSchema,
      });
      return response.data;
    },
    enabled: Boolean(organizationId),
  });

  return {
    connection: query.data,
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}
