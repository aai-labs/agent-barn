"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { createQueryKeyStructure } from "@/shared/query-keys";

import { OrganizationSettingsSchema, type OrganizationSettings } from "../schemas";

const BASE = "/api/v1/platform/settings/organizations";
const KEY = createQueryKeyStructure("platform-organization-settings").detail("settings");

/** The platform's settings for every organization. Platform Administrators only. */
export function useOrganizationSettings() {
  const client = useQueryClient();
  const settings = useQuery({
    queryKey: KEY,
    queryFn: async () => (await api.get<OrganizationSettings>(BASE, { schema: OrganizationSettingsSchema })).data,
  });
  const save = useMutation({
    mutationFn: async (settings: { defaultAgentLimit: number }) =>
      (await api.put<OrganizationSettings>(BASE, settings, { schema: OrganizationSettingsSchema })).data,
    onSuccess: (data) => client.setQueryData(KEY, data),
  });
  return {
    organizationSettings: settings.data,
    isLoading: settings.isPending,
    error: settings.error,
    reload: settings.refetch,
    saveSettings: save.mutateAsync,
    isSaving: save.isPending,
    saveError: save.error,
    resetSave: save.reset,
  };
}
