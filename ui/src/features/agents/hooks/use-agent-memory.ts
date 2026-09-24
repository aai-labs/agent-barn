"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import { z } from "zod";

import {
  AgentMemoryItem,
  AgentMemoryItemSchema,
  AgentMemoryPage,
  AgentMemoryPageSchema,
} from "../schemas";
import { agentsKey } from "../utils";

export type MemoryScope = "pool" | "mine";

export function useAgentMemory(
  agentId: string | undefined,
  page = 1,
  size = 50,
  observed: string | null = null,
  scope: MemoryScope = "pool",
) {
  const queryClient = useQueryClient();
  const orgApiBase = useOrganizationApiBase();
  const base = `${orgApiBase}/agents/${agentId}/memory`;

  const query = useQuery({
    queryKey: agentsKey.memory(agentId ?? "", page, observed, scope),
    queryFn: async () => {
      const params = new URLSearchParams({ page: String(page), size: String(size), scope });
      if (observed) params.set("observed", observed);
      const response = await api.get<AgentMemoryPage>(`${base}?${params.toString()}`, {
        schema: AgentMemoryPageSchema,
      });
      return response.data;
    },
    enabled: !!agentId,
    // Keep the last page visible while the next filter/page loads, so switching a
    // filter does not blank the list to a skeleton on every click.
    placeholderData: (prev) => prev,
  });

  // A predicate over this agent's detail keys, matching every memory-related
  // query — the paged list, the facet counts, and search — so a forget or correct
  // refreshes all three, since each reflects the change (the counts especially).
  const detailPrefix = agentsKey.detail(agentId ?? "");
  const invalidate = () =>
    void queryClient.invalidateQueries({
      predicate: (q) => {
        const k = q.queryKey;
        if (!Array.isArray(k) || k.length <= detailPrefix.length) return false;
        const matchesAgent = detailPrefix.every((part, i) => k[i] === part);
        return matchesAgent && String(k[detailPrefix.length] ?? "").startsWith("memory");
      },
    });

  const forget = useMutation({
    mutationFn: async (memoryId: string) => {
      await api.delete(`${base}/${memoryId}`);
    },
    onSuccess: invalidate,
  });

  // Honcho has no update endpoint, so the API replaces the item: the correction
  // comes back with a new id and always as "explicit", because a level cannot be
  // set on create. Refetching rather than patching in place keeps the list honest.
  const correct = useMutation({
    mutationFn: async ({ memoryId, content }: { memoryId: string; content: string }) => {
      const response = await api.put<AgentMemoryItem>(
        `${base}/${memoryId}`,
        { content },
        { schema: AgentMemoryItemSchema },
      );
      return response.data;
    },
    onSuccess: invalidate,
  });

  return {
    memory: query.data,
    isLoading: query.isPending,
    error: query.error,
    forget,
    correct,
  };
}

export function useAgentMemorySearch(agentId: string | undefined, query: string, scope: MemoryScope = "pool") {
  const orgApiBase = useOrganizationApiBase();
  const trimmed = query.trim();

  return useQuery({
    queryKey: [...agentsKey.detail(agentId ?? ""), "memory-search", scope, trimmed],
    queryFn: async () => {
      const response = await api.get<AgentMemoryItem[]>(
        `${orgApiBase}/agents/${agentId}/memory/search?q=${encodeURIComponent(trimmed)}&limit=20&scope=${scope}`,
        { schema: z.array(AgentMemoryItemSchema) },
      );
      return response.data;
    },
    // Semantic search is a vector query per peer pair, so it only runs on a
    // deliberate query rather than on every keystroke.
    enabled: !!agentId && trimmed.length > 2,
  });
}

/** The peer facets for an agent, fetched independent of the active page or filter.
 *
 *  The main list only returns facets on the unfiltered request, but the tab needs
 *  the chips to stay visible under a filter — so they live in their own cached
 *  query keyed only by agent, refetched when memory is invalidated. A size-1
 *  unfiltered read is enough: the API computes facets regardless of page size. */
export function useAgentMemoryFacets(agentId: string | undefined, scope: MemoryScope = "pool") {
  const orgApiBase = useOrganizationApiBase();

  const query = useQuery({
    queryKey: agentsKey.memoryFacets(agentId ?? "", scope),
    queryFn: async () => {
      const response = await api.get<AgentMemoryPage>(
        `${orgApiBase}/agents/${agentId}/memory?page=1&size=1&scope=${scope}`,
        { schema: AgentMemoryPageSchema },
      );
      return response.data.facets;
    },
    enabled: !!agentId,
  });

  return query.data ?? [];
}
