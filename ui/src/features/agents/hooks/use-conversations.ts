"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { ConversationsRead, ConversationsReadSchema } from "../schemas";
import { agentsKey } from "../utils";

export function useConversations(agentId: string) {
  const query = useQuery({
    queryKey: [...agentsKey.detail(agentId), "conversations"],
    queryFn: async () => {
      const response = await api.get<ConversationsRead>(
        `/api/v1/agents/${agentId}/conversations`,
        { schema: ConversationsReadSchema },
      );
      return response.data;
    },
    enabled: !!agentId,
  });

  return {
    conversations: query.data ?? null,
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}
