"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { createQueryKeyStructure } from "@/shared/query-keys";

import {
  PlatformMemoryModelsSchema,
  PlatformMemorySettingsSchema,
  type PlatformMemoryModels,
  type PlatformMemorySettings,
} from "../schemas";

const BASE = "/api/v1/platform/settings/agent-memory";
const keys = createQueryKeyStructure("platform-memory-settings");
const KEY = keys.detail("settings");

export function usePlatformMemorySettings() {
  const client = useQueryClient();
  const settings = useQuery({
    queryKey: KEY,
    queryFn: async () =>
      (
        await api.get<PlatformMemorySettings>(BASE, {
          schema: PlatformMemorySettingsSchema,
        })
      ).data,
  });
  const models = useQuery({
    queryKey: keys.detail("models"),
    queryFn: async () =>
      (
        await api.get<PlatformMemoryModels>(`${BASE}/models`, {
          schema: PlatformMemoryModelsSchema,
        })
      ).data,
  });
  const save = useMutation({
    mutationFn: async (model: string) =>
      (
        await api.put<PlatformMemorySettings>(
          BASE,
          { model },
          { schema: PlatformMemorySettingsSchema },
        )
      ).data,
    onSuccess: async (data) => {
      client.setQueryData(KEY, data);
      await client.invalidateQueries({ queryKey: KEY });
    },
  });
  return {
    memorySettings: settings.data,
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
