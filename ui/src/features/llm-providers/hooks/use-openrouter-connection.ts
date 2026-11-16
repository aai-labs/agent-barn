"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { createQueryKeyStructure } from "@/shared/query-keys";

import { OpenRouterConnectionSchema, type OpenRouterConnection } from "../schemas";

const BASE = "/api/v1/platform/settings/llm-providers/openrouter";
const KEY = createQueryKeyStructure("platform-llm-providers").detail("openrouter");

export function useOpenRouterConnection() {
  const client = useQueryClient();
  const connection = useQuery({
    queryKey: KEY,
    queryFn: async () =>
      (await api.get<OpenRouterConnection>(BASE, { schema: OpenRouterConnectionSchema })).data,
  });
  const replace = useMutation({
    mutationFn: async (apiKey: string) =>
      (await api.put<OpenRouterConnection>(BASE, { apiKey }, { schema: OpenRouterConnectionSchema })).data,
    onSuccess: async (data) => {
      client.setQueryData(KEY, data);
      await client.invalidateQueries({ queryKey: KEY });
    },
  });
  return {
    connection: connection.data,
    isLoading: connection.isPending,
    error: connection.error,
    reload: connection.refetch,
    replaceKey: replace.mutateAsync,
    isReplacing: replace.isPending,
    replaceError: replace.error,
    resetReplace: replace.reset,
  };
}
