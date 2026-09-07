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
  SharedFactResult,
  SharedFactResultSchema,
} from "../schemas";
import { agentsKey } from "../utils";

export function useAgentMemory(agentId: string | undefined, page = 1, size = 50) {
  const queryClient = useQueryClient();
  const orgApiBase = useOrganizationApiBase();
  const base = `${orgApiBase}/agents/${agentId}/memory`;

  const query = useQuery({
    queryKey: agentsKey.memory(agentId ?? "", page),
    queryFn: async () => {
      const response = await api.get<AgentMemoryPage>(`${base}?page=${page}&size=${size}`, {
        schema: AgentMemoryPageSchema,
      });
      return response.data;
    },
    enabled: !!agentId,
  });

  const invalidate = () =>
    void queryClient.invalidateQueries({ queryKey: [...agentsKey.detail(agentId ?? ""), "memory"] });

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

  // Sharing writes into the *destination* agents, so this agent's own memory list
  // is unchanged by it — nothing to invalidate here.
  const share = useMutation({
    mutationFn: async ({ content, targetAgentIds }: { content: string; targetAgentIds: string[] }) => {
      const response = await api.post<SharedFactResult>(
        `${base}/shared-facts`,
        { content, targetAgentIds },
        { schema: SharedFactResultSchema },
      );
      return response.data;
    },
  });

  return {
    memory: query.data,
    isLoading: query.isPending,
    error: query.error,
    forget,
    correct,
    share,
  };
}

export function useAgentMemorySearch(agentId: string | undefined, query: string) {
  const orgApiBase = useOrganizationApiBase();
  const trimmed = query.trim();

  return useQuery({
    queryKey: [...agentsKey.detail(agentId ?? ""), "memory-search", trimmed],
    queryFn: async () => {
      const response = await api.get<AgentMemoryItem[]>(
        `${orgApiBase}/agents/${agentId}/memory/search?q=${encodeURIComponent(trimmed)}&limit=20`,
        { schema: z.array(AgentMemoryItemSchema) },
      );
      return response.data;
    },
    // Semantic search is a vector query per peer pair, so it only runs on a
    // deliberate query rather than on every keystroke.
    enabled: !!agentId && trimmed.length > 2,
  });
}
