"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import {
  ConversationChannel,
  ConversationChannelSchema,
  ConversationThreadsPage,
  ConversationThreadsPageSchema,
  ConversationsCursor,
} from "../schemas";
import {
  CONVERSATION_MESSAGES_PAGE_SIZE,
  ConversationsFiltersKey,
  agentsKey,
} from "../utils";
import { z } from "zod";

const ChannelsListSchema = z.array(ConversationChannelSchema);

export function useConversationChannels(agentId: string) {
  const query = useQuery({
    queryKey: agentsKey.conversationChannels(agentId),
    queryFn: async () => {
      const response = await api.get<ConversationChannel[]>(
        `/api/v1/agents/${agentId}/conversations/channels`,
        { schema: ChannelsListSchema },
      );
      return response.data;
    },
    enabled: !!agentId,
  });

  return {
    channels: query.data ?? [],
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}

export function useChannelMessages(
  agentId: string,
  channelId: string | null,
  filters: ConversationsFiltersKey,
) {
  const query = useInfiniteQuery({
    queryKey: channelId
      ? agentsKey.conversationMessages(agentId, channelId, filters)
      : ["disabled-conversation-messages"],
    queryFn: async ({ pageParam }) => {
      const params = new URLSearchParams();
      params.set("page_size", String(CONVERSATION_MESSAGES_PAGE_SIZE));
      if (filters.fromDate) params.set("from_date", filters.fromDate);
      if (filters.toDate) params.set("to_date", filters.toDate);
      if (pageParam?.beforeOccurredAt) {
        params.set("before_occurred_at", pageParam.beforeOccurredAt);
      }
      if (pageParam?.beforeId) {
        params.set("before_id", pageParam.beforeId);
      }
      const response = await api.get<ConversationThreadsPage>(
        `/api/v1/agents/${agentId}/conversations/channels/${channelId}/messages?${params.toString()}`,
        { schema: ConversationThreadsPageSchema },
      );
      return response.data;
    },
    initialPageParam: null as ConversationsCursor | null,
    getNextPageParam: (lastPage) =>
      lastPage.hasMore ? lastPage.nextCursor : undefined,
    enabled: !!agentId && !!channelId,
  });

  return query;
}
