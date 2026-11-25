"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";

import {
  LlmProviderOrganizationsSchema,
  type LlmProviderOrganizations,
  type OrganizationsReplacement,
} from "../schemas";
import { connectionUrl, llmProvidersKey } from "./use-llm-provider-connections";

function organizationsKey(slug: string) {
  return [...llmProvidersKey.detail(slug), "organizations"] as const;
}

export function useLlmProviderOrganizations(slug: string, enabled: boolean) {
  const query = useQuery({
    queryKey: organizationsKey(slug),
    enabled,
    queryFn: async () =>
      (
        await api.get<LlmProviderOrganizations>(`${connectionUrl(slug)}/organizations`, {
          schema: LlmProviderOrganizationsSchema,
        })
      ).data,
  });
  return {
    providerOrganizations: query.data,
    isLoadingProviderOrganizations: !query.isFetchedAfterMount,
    providerOrganizationsError: query.error,
    reloadProviderOrganizations: query.refetch,
  };
}

export function useLlmProviderOrganizationActions(slug: string) {
  const client = useQueryClient();
  const save = useMutation({
    mutationFn: async (replacement: OrganizationsReplacement) =>
      (
        await api.put<LlmProviderOrganizations>(`${connectionUrl(slug)}/organizations`, replacement, {
          schema: LlmProviderOrganizationsSchema,
        })
      ).data,
    onSuccess: () => client.invalidateQueries({ queryKey: llmProvidersKey.all }),
  });
  return {
    saveOrganizations: save.mutateAsync,
    isSavingOrganizations: save.isPending,
    saveOrganizationsError: save.error,
    resetSaveOrganizations: save.reset,
  };
}
