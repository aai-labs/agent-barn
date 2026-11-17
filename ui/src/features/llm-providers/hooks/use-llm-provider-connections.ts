"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { createQueryKeyStructure } from "@/shared/query-keys";

import {
  LlmProviderConnectionListSchema,
  LlmProviderConnectionSchema,
  type KeyReplacement,
  type LlmProviderConnection,
  type NewLlmProviderConnection,
} from "../schemas";

const BASE = "/api/v1/platform/settings/llm-providers";

export const llmProvidersKey = createQueryKeyStructure("platform-llm-providers");

function connectionUrl(slug: string) {
  return `${BASE}/${encodeURIComponent(slug)}`;
}

export function useLlmProviderConnections() {
  const connections = useQuery({
    queryKey: llmProvidersKey.list(),
    queryFn: async () =>
      (await api.get<LlmProviderConnection[]>(BASE, { schema: LlmProviderConnectionListSchema })).data,
  });
  return {
    connections: connections.data,
    isLoadingConnections: connections.isPending,
    connectionsError: connections.error,
    reloadConnections: connections.refetch,
  };
}

export function useLlmProviderActions() {
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: llmProvidersKey.all });
  const add = useMutation({
    mutationFn: async (connection: NewLlmProviderConnection) =>
      (await api.post<LlmProviderConnection>(BASE, connection, { schema: LlmProviderConnectionSchema })).data,
    onSuccess: refresh,
  });
  const replace = useMutation({
    mutationFn: async ({ slug, ...replacement }: KeyReplacement & { slug: string }) =>
      (
        await api.put<LlmProviderConnection>(`${connectionUrl(slug)}/key`, replacement, {
          schema: LlmProviderConnectionSchema,
        })
      ).data,
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: async (slug: string) => {
      await api.delete(connectionUrl(slug));
    },
    onSuccess: refresh,
  });
  return {
    addConnection: add.mutateAsync,
    isAdding: add.isPending,
    addError: add.error,
    resetAdd: add.reset,
    replaceKey: replace.mutateAsync,
    isReplacing: replace.isPending,
    replaceError: replace.error,
    resetReplace: replace.reset,
    deleteConnection: remove.mutateAsync,
    isDeleting: remove.isPending,
    deleteError: remove.error,
    resetDelete: remove.reset,
  };
}
