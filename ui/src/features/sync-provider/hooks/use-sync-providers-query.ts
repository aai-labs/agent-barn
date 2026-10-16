"use client";

import { useQuery } from "@tanstack/react-query";
import { z } from "zod";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";

import { SyncProviderSchema, type SyncProvider } from "../schemas";
import { syncProviderKey } from "../utils";

export function useSyncProvidersQuery() {
  const orgApiBase = useOrganizationApiBase();
  const { selectedOrganization } = useOrganizationContext();
  const organizationId = selectedOrganization?.id ?? "";

  const query = useQuery({
    queryKey: syncProviderKey.detail(organizationId),
    queryFn: async () => {
      const response = await api.get<SyncProvider[]>(`${orgApiBase}/sync-providers`, {
        schema: z.array(SyncProviderSchema),
      });
      return response.data;
    },
    enabled: Boolean(organizationId),
  });

  return {
    providers: query.data,
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}
