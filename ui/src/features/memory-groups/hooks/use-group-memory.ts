"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import {
  type AgentMemoryItem,
  AgentMemoryItemSchema,
  type AgentMemoryPage,
  AgentMemoryPageSchema,
} from "@/features/agents/schemas";

import { memoryGroupsKey } from "../utils";

// The group's pooled memory reuses the agent memory contracts — it's the same
// Honcho conclusions, just read through the group's pool workspace instead of an
// agent's. The endpoints live under /memory-groups/{id}/memory.
function memoryBase(orgApiBase: string, groupId: string) {
  return `${orgApiBase}/memory-groups/${groupId}/memory`;
}

export function useGroupMemory(groupId: string, page = 1, size = 50, observed: string | null = null) {
  const queryClient = useQueryClient();
  const orgApiBase = useOrganizationApiBase();
  const base = memoryBase(orgApiBase, groupId);

  const query = useQuery({
    queryKey: [...memoryGroupsKey.detail(groupId), "memory", observed ?? "everyone", page],
    queryFn: async () => {
      const params = new URLSearchParams({ page: String(page), size: String(size) });
      if (observed) params.set("observed", observed);
      const response = await api.get<AgentMemoryPage>(`${base}?${params.toString()}`, {
        schema: AgentMemoryPageSchema,
      });
      return response.data;
    },
    placeholderData: (prev) => prev,
  });

  // Curation changes what the whole pool knows, so refresh the paged list, the
  // facet counts, and search together.
  const detailPrefix = memoryGroupsKey.detail(groupId);
  const invalidate = () =>
    void queryClient.invalidateQueries({
      predicate: (q) => {
        const k = q.queryKey;
        if (!Array.isArray(k) || k.length <= detailPrefix.length) return false;
        const matchesGroup = detailPrefix.every((part, i) => k[i] === part);
        return matchesGroup && String(k[detailPrefix.length] ?? "").startsWith("memory");
      },
    });

  const forget = useMutation({
    mutationFn: async (memoryId: string) => {
      await api.delete(`${base}/${memoryId}`);
    },
    onSuccess: invalidate,
  });

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

  return { memory: query.data, isLoading: query.isPending, error: query.error, forget, correct };
}

export function useGroupMemorySearch(groupId: string, query: string) {
  const orgApiBase = useOrganizationApiBase();
  const trimmed = query.trim();

  return useQuery({
    queryKey: [...memoryGroupsKey.detail(groupId), "memory-search", trimmed],
    queryFn: async () => {
      const response = await api.get<AgentMemoryItem[]>(
        `${memoryBase(orgApiBase, groupId)}/search?q=${encodeURIComponent(trimmed)}&limit=20`,
        { schema: z.array(AgentMemoryItemSchema) },
      );
      return response.data;
    },
    enabled: trimmed.length > 2,
  });
}

/** Facets in their own cached query so the chips persist under a peer filter — the
 *  paged response only carries facets when unfiltered. */
export function useGroupMemoryFacets(groupId: string) {
  const orgApiBase = useOrganizationApiBase();
  const query = useQuery({
    queryKey: [...memoryGroupsKey.detail(groupId), "memory-facets"],
    queryFn: async () => {
      const response = await api.get<AgentMemoryPage>(`${memoryBase(orgApiBase, groupId)}?page=1&size=1`, {
        schema: AgentMemoryPageSchema,
      });
      return response.data.facets;
    },
  });
  return query.data ?? [];
}
