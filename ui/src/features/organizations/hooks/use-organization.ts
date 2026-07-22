"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { type Organization, OrganizationSchema } from "../schemas";
import { organizationsKey } from "../utils";

export function useOrganization(organizationId: string) {
  const query = useQuery({
    queryKey: organizationsKey.detail(organizationId),
    queryFn: async () => {
      const response = await api.get<Organization>(
        `/api/v1/organizations/${organizationId}`,
        { schema: OrganizationSchema },
      );
      return response.data;
    },
    enabled: !!organizationId,
  });

  return { organization: query.data ?? null, isLoading: query.isPending };
}
