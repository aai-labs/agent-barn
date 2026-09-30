"use client";

import { useQuery } from "@tanstack/react-query";
import { z } from "zod";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import { ModelOption, ModelOptionSchema } from "../schemas";
import { agentsKey } from "../utils";

// Shown while the catalogue loads and as a safety net if the fetch fails, so
// the picker is never empty. Kept in sync with AGENT_DEFAULT_MODEL.
export const FALLBACK_MODELS: ModelOption[] = [
  { value: "litellm/openrouter/z-ai/glm-5.2", label: "GLM 5.2", isDefault: true },
  { value: "litellm/openrouter/openai/gpt-5-mini", label: "GPT-5 mini" },
];

export function useModels({ catalog = false }: { catalog?: boolean } = {}) {
  const orgApiBase = useOrganizationApiBase();
  const query = useQuery({
    queryKey: [...agentsKey.models(), { catalog }],
    queryFn: async () => {
      const response = await api.get<ModelOption[]>(
        `${orgApiBase}/agents/models${catalog ? "?catalog=true" : ""}`,
        {
          schema: z.array(ModelOptionSchema),
        },
      );
      return response.data;
    },
    // The response carries the Organization's resolved default. It must be refreshed
    // whenever a picker mounts so “Use organization default” never describes a model
    // another owner changed in a different session.
    staleTime: 0,
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
