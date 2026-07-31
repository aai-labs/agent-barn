"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import {
  type PlatformOrganization,
  PlatformOrganizationSchema,
} from "../schemas";
import { organizationsKey } from "../utils";

export function usePlatformOrganization(organizationId: string) {
  const query = useQuery({
    queryKey: organizationsKey.detail(organizationId),
    queryFn: async () => {
      const response = await api.get<PlatformOrganization>(
        `/api/v1/platform/organizations/${organizationId}`,
        { schema: PlatformOrganizationSchema },
      );
      return response.data;
    },
    enabled: !!organizationId,
  });

  return {
    organization: query.data ?? null,
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}
