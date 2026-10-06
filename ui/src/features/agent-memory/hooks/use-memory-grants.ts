"use client";

import { useQuery } from "@tanstack/react-query";

import { PaginatedAgentsSchema, type PaginatedAgents } from "@/features/agents/schemas";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { api } from "@/shared/api";

import { MemoryGrantListSchema, type MemoryGrant } from "../schemas";
import { MEMORY_AGENT_OPTIONS_PAGE_SIZE, agentMemoryKey, memoryGrantsKey } from "../utils";

/** Requires `memory.access.manage`; pass `enabled: false` for anyone without it. */
export function useMemoryGrants(enabled: boolean) {
  const orgApiBase = useOrganizationApiBase();
  const query = useQuery({
    queryKey: memoryGrantsKey.forOrganization(orgApiBase),
    queryFn: async () => {
      const response = await api.get<MemoryGrant[]>(`${orgApiBase}/memory-grants`, {
        schema: MemoryGrantListSchema,
      });
      return response.data;
    },
    enabled,
  });

  return {
    grants: query.data ?? [],
    isLoading: query.isPending && query.fetchStatus !== "idle",
    error: query.error,
    refetch: query.refetch,
  };
}

/** Agents a grant can name, as `{id, name}` pairs. */
export function useMemoryAgentOptions(enabled: boolean) {
  const orgApiBase = useOrganizationApiBase();
  const query = useQuery({
    queryKey: agentMemoryKey.agentOptions(orgApiBase),
    queryFn: async () => {
      const response = await api.get<PaginatedAgents>(
        `${orgApiBase}/agents?page=1&page_size=${MEMORY_AGENT_OPTIONS_PAGE_SIZE}`,
        { schema: PaginatedAgentsSchema },
      );
      return response.data;
    },
    enabled,
  });

  return {
    agents: (query.data?.items ?? []).map((agent) => ({ id: agent.id, name: agent.name })),
    truncated: (query.data?.total ?? 0) > (query.data?.items.length ?? 0),
    isLoading: query.isPending && query.fetchStatus !== "idle",
    error: query.error,
    refetch: query.refetch,
  };
}
