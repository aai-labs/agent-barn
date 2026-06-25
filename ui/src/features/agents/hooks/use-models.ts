"use client";

import { useQuery } from "@tanstack/react-query";
import { z } from "zod";

import { api } from "@/shared/api";

import { ModelOption, ModelOptionSchema } from "../schemas";
import { agentsKey } from "../utils";

// Shown while the catalogue loads and as a safety net if the fetch fails, so
// the picker is never empty. Kept in sync with AGENT_DEFAULT_MODEL.
export const FALLBACK_MODELS: ModelOption[] = [
  { value: "litellm/openrouter/qwen/qwen3.6-plus", label: "Qwen3.6 Plus", isDefault: true },
  { value: "litellm/openrouter/openai/gpt-5-mini", label: "GPT-5 mini" },
];

export function useModels() {
  const query = useQuery({
    queryKey: agentsKey.models(),
    queryFn: async () => {
      const response = await api.get<ModelOption[]>("/api/v1/agents/models", {
        schema: z.array(ModelOptionSchema),
      });
      return response.data;
    },
    staleTime: 60 * 60_000,
  });

  const models = query.data?.length ? query.data : FALLBACK_MODELS;
  const defaultModel =
    models.find((m) => m.isDefault)?.value ?? models[0]?.value ?? "";

  return {
    models,
    defaultModel,
    isLoading: query.isPending,
    error: query.error,
  };
}
