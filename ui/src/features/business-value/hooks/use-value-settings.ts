"use client";

import { useQuery } from "@tanstack/react-query";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";
import { api } from "@/shared/api";

import { ValueSettingsSchema, type ValueSettings } from "../schemas";
import { valueSettingsKey } from "../utils";

export function useValueSettings() {
  const orgApiBase = useOrganizationApiBase();
  const { selectedOrganization } = useOrganizationContext();
  const organizationId = selectedOrganization?.id ?? "";

  const query = useQuery({
    queryKey: valueSettingsKey.detail(organizationId),
    queryFn: async () => {
      const response = await api.get<ValueSettings>(`${orgApiBase}/value-settings`, {
        schema: ValueSettingsSchema,
      });
      return response.data;
    },
    enabled: Boolean(organizationId),
  });

  return {
    settings: query.data ?? null,
    isLoadingSettings: query.isPending,
    settingsError: query.error,
    refetchSettings: query.refetch,
  };
}
