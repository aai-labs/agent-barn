"use client";

import { useQuery } from "@tanstack/react-query";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";
import { api } from "@/shared/api";

import { OrganizationActivitySchema, type OrganizationActivity } from "../schemas";
import { organizationActivityKey, windowQuery, type KpiWindow } from "../utils";

export function useOrganizationActivity(range: KpiWindow) {
  const orgApiBase = useOrganizationApiBase();
  const { selectedOrganization } = useOrganizationContext();
  const organizationId = selectedOrganization?.id ?? "";

  const query = useQuery({
    queryKey: organizationActivityKey.list({ scope: { organizationId }, filters: range }),
    queryFn: async () => {
      const response = await api.get<OrganizationActivity>(
        `${orgApiBase}/value/activity${windowQuery(range)}`,
        { schema: OrganizationActivitySchema },
      );
      return response.data;
    },
    enabled: Boolean(organizationId),
  });

  return {
    activity: query.data ?? null,
    isLoadingActivity: query.isPending,
    activityError: query.error,
    refetchActivity: query.refetch,
  };
}
