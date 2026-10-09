"use client";

import { useQuery } from "@tanstack/react-query";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";
import { api } from "@/shared/api";

import { OrganizationValueSchema, type OrganizationValue } from "../schemas";
import { organizationValueKey, windowQuery, type KpiWindow } from "../utils";

export function useOrganizationValue(range: KpiWindow) {
  const orgApiBase = useOrganizationApiBase();
  const { selectedOrganization } = useOrganizationContext();
  const organizationId = selectedOrganization?.id ?? "";

  const query = useQuery({
    queryKey: organizationValueKey.list({ scope: { organizationId }, filters: range }),
    queryFn: async () => {
      const response = await api.get<OrganizationValue>(
        `${orgApiBase}/value${windowQuery(range)}`,
        { schema: OrganizationValueSchema },
      );
      return response.data;
    },
    enabled: Boolean(organizationId),
  });

  return {
    value: query.data ?? null,
    isLoadingValue: query.isPending,
    valueError: query.error,
    refetchValue: query.refetch,
  };
}
