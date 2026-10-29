"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { createQueryKeyStructure } from "@/shared/query-keys";

import { PlatformWorkflowSettingsSchema, type PlatformWorkflowSettings } from "../schemas";
import { workflowsKey } from "./use-workflows";

const BASE = "/api/v1/platform/settings/workflows";
const KEY = createQueryKeyStructure("platform-workflow-settings").detail("settings");

export function usePlatformWorkflowSettings() {
  const client = useQueryClient();
  const settings = useQuery({
    queryKey: KEY,
    queryFn: async () => (await api.get<PlatformWorkflowSettings>(BASE, {
      schema: PlatformWorkflowSettingsSchema,
    })).data,
  });
  const save = useMutation({
    mutationFn: async (authoringEnabled: boolean) => (await api.put<PlatformWorkflowSettings>(
      BASE, { authoringEnabled }, { schema: PlatformWorkflowSettingsSchema },
    )).data,
    onSuccess: async (data) => {
      client.setQueryData(KEY, data);
      await Promise.all([
        client.invalidateQueries({ queryKey: KEY }),
        client.invalidateQueries({ queryKey: workflowsKey.all }),
      ]);
    },
  });
  return {
    settings: settings.data,
    isLoading: settings.isPending,
    error: settings.error,
    reload: settings.refetch,
    save: save.mutateAsync,
    isSaving: save.isPending,
    saveError: save.error,
    resetSave: save.reset,
  };
}
