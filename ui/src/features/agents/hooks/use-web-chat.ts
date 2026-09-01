"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { camelizeKeys } from "humps";
import { z } from "zod";

import { api } from "@/shared/api";
import { useAuthStore } from "@/auth/providers/auth-store";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import { WebChatMessageSchema, type WebChatMessage } from "../schemas";
import { agentsKey } from "../utils";

export const MAIN_THREAD_ID = "main";

const MessagesListSchema = z.array(WebChatMessageSchema);

const RECONNECT_BASE_MS = 1_000;
const RECONNECT_MAX_MS = 15_000;

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
        if (base.some((m) => m.id === message.id)) return base;
        return [...base, message];
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

  const [streamStatus, setStreamStatus] = useState<
    "idle" | "connecting" | "streaming" | "disconnected"
  >("idle");

  useEffect(() => {
    if (!enabled || !agentId || !threadId || historyQuery.isPending) return;

    const controller = new AbortController();
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let retries = 0;
    let cancelled = false;

    async function connect() {
      if (cancelled) return;
      setStreamStatus("connecting");

      const tokens = useAuthStore.getState().authToken;
      if (!tokens?.accessToken) {
        setStreamStatus("disconnected");
        return;
      }

      try {
        const response = await fetch(
          `${orgApiBase}/agents/${agentId}/web-chat/stream?thread_id=${encodeURIComponent(threadId)}`,
          {
            headers: {
              Authorization: `Bearer ${tokens.accessToken}`,
              Accept: "text/event-stream",
            },
            signal: controller.signal,
          },
        );

        if (!response.ok || !response.body) {
          setStreamStatus("disconnected");
          scheduleReconnect();
          return;
        }

        setStreamStatus("streaming");
        retries = 0;

        const reader = response.body
          .pipeThrough(new TextDecoderStream())
          .getReader();

        let buffer = "";
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += value;
          const parts = buffer.split("\n\n");
          buffer = parts.pop() ?? "";
          for (const part of parts) {
            for (const line of part.split("\n")) {
              if (!line.startsWith("data: ")) continue;
              try {
                const parsed = WebChatMessageSchema.parse(
                  camelizeKeys(JSON.parse(line.slice(6))),
                );
                appendMessage(parsed);
              } catch {
                // Ignore malformed frames rather than dropping the stream.
              }
            }
          }
        }

        if (!cancelled) {
          setStreamStatus("disconnected");
          scheduleReconnect();
        }
      } catch (err) {
        if ((err as DOMException).name === "AbortError") return;
        if (!cancelled) {
          setStreamStatus("disconnected");
          scheduleReconnect();
        }
      }
    }

    function scheduleReconnect() {
      if (cancelled) return;
      const delay = Math.min(RECONNECT_BASE_MS * 2 ** retries, RECONNECT_MAX_MS);
      retries += 1;
      reconnectTimer = setTimeout(() => void connect(), delay);
    }

    void connect();

    return () => {
      cancelled = true;
      controller.abort();
      if (reconnectTimer) clearTimeout(reconnectTimer);
    };
  }, [agentId, threadId, enabled, historyQuery.isPending, orgApiBase, appendMessage]);

  const isAwaitingReply =
    sendMutation.isPending || messages.at(-1)?.direction === "INBOUND";

  return useMemo(
    () => ({
      messages,
      isLoading: historyQuery.isPending,
      error: historyQuery.error,
      streamStatus,
      sendMessage,
      isAwaitingReply,
    }),
    [
      messages,
      historyQuery.isPending,
      historyQuery.error,
      streamStatus,
      sendMessage,
      isAwaitingReply,
    ],
  );
}
