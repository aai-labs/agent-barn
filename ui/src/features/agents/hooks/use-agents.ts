"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import { PaginatedAgents, PaginatedAgentsSchema } from "../schemas";
import { AGENTS_PAGE_SIZE, agentsKey } from "../utils";

export function useAgents() {
  const orgApiBase = useOrganizationApiBase();
  const query = useQuery({
    queryKey: agentsKey.list(),
    queryFn: async () => {
      const params = new URLSearchParams();
      params.set("page", "1");
      params.set("page_size", String(AGENTS_PAGE_SIZE));
      const response = await api.get<PaginatedAgents>(
        `${orgApiBase}/agents?${params.toString()}`,
        { schema: PaginatedAgentsSchema },
      );
      return response.data;
    },
  });

  return {
    agents: query.data?.items ?? [],
    total: query.data?.total ?? 0,
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}
