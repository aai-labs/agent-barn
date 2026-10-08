"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { createQueryKeyStructure } from "@/shared/query-keys";

import { TrialSettingsSchema, type TrialSettings } from "../schemas";

const BASE = "/api/v1/platform/settings/trial";
const KEY = createQueryKeyStructure("platform-trial-settings").detail("settings");

export function useTrialSettings() {
  const client = useQueryClient();
  const settings = useQuery({
    queryKey: KEY,
    queryFn: async () => (await api.get<TrialSettings>(BASE, { schema: TrialSettingsSchema })).data,
  });
  const save = useMutation({
    mutationFn: async (settings: { creditUsd: number; agentLimit: number }) =>
      (await api.put<TrialSettings>(BASE, settings, { schema: TrialSettingsSchema })).data,
    onSuccess: (data) => client.setQueryData(KEY, data),
  });
  return {
    trialSettings: settings.data,
    isLoadingTrialSettings: settings.isPending,
    trialSettingsError: settings.error,
    reloadTrialSettings: settings.refetch,
    saveSettings: save.mutateAsync,
    isSaving: save.isPending,
    saveError: save.error,
    resetSave: save.reset,
  };
}
