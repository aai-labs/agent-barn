"use client";

import { useCallback, useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { camelizeKeys } from "humps";
import { z } from "zod";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import { WebChatMessageSchema, type WebChatMessage } from "../schemas";
import { agentsKey } from "../utils";
import { useSseStream } from "./use-sse-stream";

export const MAIN_THREAD_ID = "main";

const MessagesListSchema = z.array(WebChatMessageSchema);

export function useWebChat(
  agentId: string,
  threadId: string,
  enabled: boolean,
) {
  const orgApiBase = useOrganizationApiBase();
  const queryClient = useQueryClient();
  // Stable identity across renders — appendMessage (below) closes over this
  // and is itself an effect dependency; a fresh array here every render was
  // tearing down and reopening the SSE connection on every render.
  const queryKey = useMemo(
    () => agentsKey.webChatMessages(agentId, threadId),
    [agentId, threadId],
  );

  const historyQuery = useQuery({
    queryKey,
    queryFn: async () => {
      const response = await api.get<WebChatMessage[]>(
        `${orgApiBase}/agents/${agentId}/web-chat/messages`,
        { params: { thread_id: threadId }, schema: MessagesListSchema },
      );
      return response.data;
    },
    enabled: enabled && !!agentId && !!threadId,
    staleTime: Infinity,
  });

  const messages = useMemo(() => historyQuery.data ?? [], [historyQuery.data]);

  const appendMessage = useCallback(
    (message: WebChatMessage) => {
      queryClient.setQueryData<WebChatMessage[]>(queryKey, (current) => {
        const base = current ?? [];
        const existingIndex = base.findIndex((item) => item.id === message.id);
        if (existingIndex === -1) return [...base, message];
        if (
          base[existingIndex].deliveryStatus === message.deliveryStatus
          && base[existingIndex].cancelRequestedAt === message.cancelRequestedAt
        ) return base;
        return base.map((item, index) => (index === existingIndex ? message : item));
      });
    },
    [queryClient, queryKey],
  );

  const sendMutation = useMutation({
    mutationFn: async (text: string) => {
      const response = await api.post<WebChatMessage>(
        `${orgApiBase}/agents/${agentId}/web-chat/messages`,
        { text, threadId },
        { schema: WebChatMessageSchema },
      );
      return response.data;
    },
  });

  const sendMessage = useCallback(
    async (text: string) => {
      const message = await sendMutation.mutateAsync(text);
      appendMessage(message);
    },
    [appendMessage, sendMutation],
  );

  const stopMutation = useMutation({
    mutationFn: async () => {
      await api.post(
        `${orgApiBase}/agents/${agentId}/web-chat/threads/${encodeURIComponent(threadId)}/stop`,
      );
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey, exact: true });
    },
  });

  const stopGeneration = useCallback(async () => {
    await stopMutation.mutateAsync();
  }, [stopMutation]);

  const streamReady = enabled && !!agentId && !!threadId && !historyQuery.isPending;

  const onStreamLine = useCallback(
    (line: string) => {
      try {
        const parsed = WebChatMessageSchema.parse(camelizeKeys(JSON.parse(line)));
        appendMessage(parsed);
      } catch {
        // Ignore malformed frames rather than dropping the stream.
      }
    },
    [appendMessage],
  );

  const { status: streamStatus } = useSseStream({
    url: streamReady
      ? `${orgApiBase}/agents/${agentId}/web-chat/stream?thread_id=${encodeURIComponent(threadId)}`
      : null,
    enabled: streamReady,
    onLine: onStreamLine,
  });

  const latestMessage = messages.at(-1);
  const isAwaitingReply =
    sendMutation.isPending ||
    (latestMessage?.direction === "INBOUND" &&
      ["PENDING", "PROCESSING"].includes(latestMessage.deliveryStatus) &&
      !latestMessage.cancelRequestedAt);

  return useMemo(
    () => ({
      messages,
      isLoading: historyQuery.isPending,
      error: historyQuery.error,
      streamStatus,
      sendMessage,
      stopGeneration,
      isAwaitingReply,
    }),
    [
      messages,
      historyQuery.isPending,
      historyQuery.error,
      streamStatus,
      sendMessage,
      stopGeneration,
      isAwaitingReply,
    ],
  );
}
