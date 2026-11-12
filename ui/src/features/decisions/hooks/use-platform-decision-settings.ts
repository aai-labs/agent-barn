"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";

import {
  PlatformDecisionModelsSchema,
  PlatformDecisionSettingsSchema,
  type PlatformDecisionModels,
  type PlatformDecisionSettings,
} from "../schemas";
import { decisionsKey } from "../utils";

const BASE = "/api/v1/platform/settings/decisions";

export function usePlatformDecisionSettings() {
  const client = useQueryClient();
  const settings = useQuery({
    queryKey: decisionsKey.platformSettings(),
    queryFn: async () =>
      (await api.get<PlatformDecisionSettings>(BASE, { schema: PlatformDecisionSettingsSchema })).data,
  });
  const models = useQuery({
    queryKey: decisionsKey.platformModels(),
    queryFn: async () =>
      (await api.get<PlatformDecisionModels>(`${BASE}/models`, { schema: PlatformDecisionModelsSchema })).data,
  });
  const save = useMutation({
    mutationFn: async (model: string) =>
      (await api.put<PlatformDecisionSettings>(BASE, { model }, { schema: PlatformDecisionSettingsSchema })).data,
    onSuccess: async (data) => {
      client.setQueryData(decisionsKey.platformSettings(), data);
      await client.invalidateQueries({ queryKey: decisionsKey.platformSettings() });
    },
  });
  return {
    settings: settings.data,
    isLoadingSettings: settings.isPending,
    settingsError: settings.error,
    reloadSettings: settings.refetch,
    availableModels: models.data ?? [],
    isLoadingModels: models.isPending,
    modelsError: models.error,
    reloadModels: models.refetch,
    saveModel: save.mutateAsync,
    isSavingModel: save.isPending,
    saveError: save.error,
    resetSave: save.reset,
  };
}
