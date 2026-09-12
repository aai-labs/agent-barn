"use client";

import { useId } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import { AgentNameSuggestionSchema, type AgentNameSuggestion } from "../schemas";
import { agentsKey } from "../utils";

export function useAgentNameSuggestion() {
  const orgApiBase = useOrganizationApiBase();
  const openingId = useId();
  const query = useQuery({
    // Each dialog owns its suggestion; invalidation must not rename an open form.
    queryKey: agentsKey.nameSuggestion(orgApiBase, openingId),
    queryFn: async () => {
      const response = await api.get<AgentNameSuggestion>(
        `${orgApiBase}/agents/name-suggestion`,
        { schema: AgentNameSuggestionSchema },
      );
      return response.data;
    },
    enabled: (query) => query.state.data === undefined,
    gcTime: 0,
    retry: false,
    refetchOnWindowFocus: false,
  });
  return {
    firstName: query.data?.firstName,
    isLoading: query.isPending && query.isFetching,
    error: query.error,
    retry: query.refetch,
  };
}
