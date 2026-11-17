"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { createQueryKeyStructure } from "@/shared/query-keys";

import {
  LlmProviderConnectionListSchema,
  LlmProviderConnectionSchema,
  type LlmProviderConnection,
  type NewLlmProviderConnection,
} from "../schemas";

const BASE = "/api/v1/platform/settings/llm-providers";

export const llmProvidersKey = createQueryKeyStructure("platform-llm-providers");

export function useLlmProviderConnections() {
  const client = useQueryClient();
  const connections = useQuery({
    queryKey: llmProvidersKey.list(),
    queryFn: async () =>
      (await api.get<LlmProviderConnection[]>(BASE, { schema: LlmProviderConnectionListSchema })).data,
  });
  const add = useMutation({
    mutationFn: async (connection: NewLlmProviderConnection) =>
      (await api.post<LlmProviderConnection>(BASE, connection, { schema: LlmProviderConnectionSchema })).data,
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: llmProvidersKey.lists() });
    },
  });
  return {
    connections: connections.data,
    isLoadingConnections: connections.isPending,
    connectionsError: connections.error,
    reloadConnections: connections.refetch,
    addConnection: add.mutateAsync,
    isAdding: add.isPending,
    addError: add.error,
    resetAdd: add.reset,
  };
}
