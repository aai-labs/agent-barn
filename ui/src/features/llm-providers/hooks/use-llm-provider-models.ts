"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";

import {
  LlmProviderCatalogueSchema,
  LlmProviderModelListSchema,
  type LlmProviderCatalogueEntry,
  type LlmProviderModel,
  type ModelChoice,
} from "../schemas";
import { connectionUrl, llmProvidersKey } from "./use-llm-provider-connections";

function modelsKey(slug: string) {
  return [...llmProvidersKey.detail(slug), "models"] as const;
}

function catalogueKey(slug: string) {
  return [...llmProvidersKey.detail(slug), "model-catalogue"] as const;
}

export function useLlmProviderModels(slug: string) {
  const stored = useQuery({
    queryKey: modelsKey(slug),
    queryFn: async () =>
      (await api.get<LlmProviderModel[]>(`${connectionUrl(slug)}/models`, { schema: LlmProviderModelListSchema })).data,
  });
  const catalogue = useQuery({
    queryKey: catalogueKey(slug),
    queryFn: async () =>
      (
        await api.get<LlmProviderCatalogueEntry[]>(`${connectionUrl(slug)}/model-catalogue`, {
          schema: LlmProviderCatalogueSchema,
        })
      ).data,
  });
  return {
    storedModels: stored.data,
    catalogue: catalogue.data,
    isLoadingModels: stored.isPending || catalogue.isPending,
    modelsError: stored.error ?? catalogue.error,
    reloadModels: () => Promise.all([stored.refetch(), catalogue.refetch()]),
  };
}

export function useLlmProviderModelActions(slug: string) {
  const client = useQueryClient();
  const save = useMutation({
    mutationFn: async (models: ModelChoice[]) =>
      (
        await api.put<LlmProviderModel[]>(
          `${connectionUrl(slug)}/models`,
          { models },
          { schema: LlmProviderModelListSchema },
        )
      ).data,
    onSuccess: () => client.invalidateQueries({ queryKey: llmProvidersKey.detail(slug) }),
  });
  return { saveModels: save.mutateAsync, isSavingModels: save.isPending, saveModelsError: save.error };
}
