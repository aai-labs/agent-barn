"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";

import {
  PlatformPlaybookModelsSchema,
  PlatformPlaybookSettingsSchema,
  type PlatformPlaybookModels,
  type PlatformPlaybookSettings,
} from "../schemas";
import { playbooksKey } from "../utils";

const BASE = "/api/v1/platform/settings/playbooks";

export function usePlatformPlaybookSettings() {
  const client = useQueryClient();
  const settings = useQuery({
    queryKey: playbooksKey.platformSettings(),
    queryFn: async () =>
      (await api.get<PlatformPlaybookSettings>(BASE, { schema: PlatformPlaybookSettingsSchema })).data,
  });
  const models = useQuery({
    queryKey: playbooksKey.platformModels(),
    queryFn: async () =>
      (await api.get<PlatformPlaybookModels>(`${BASE}/models`, { schema: PlatformPlaybookModelsSchema })).data,
  });
  const save = useMutation({
    mutationFn: async (model: string) =>
      (await api.put<PlatformPlaybookSettings>(BASE, { model }, { schema: PlatformPlaybookSettingsSchema })).data,
    onSuccess: async (data) => {
      client.setQueryData(playbooksKey.platformSettings(), data);
      await client.invalidateQueries({ queryKey: playbooksKey.platformSettings() });
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
