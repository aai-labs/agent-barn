"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import { WebChatThreadSchema, type WebChatThread } from "../schemas";
import { agentsKey } from "../utils";

const ThreadsListSchema = z.array(WebChatThreadSchema);

export function useWebChatThreads(agentId: string, enabled: boolean) {
  const orgApiBase = useOrganizationApiBase();
  const queryClient = useQueryClient();
  const queryKey = agentsKey.webChatThreads(agentId);

  const query = useQuery({
    queryKey,
    queryFn: async () => {
      const response = await api.get<WebChatThread[]>(
        `${orgApiBase}/agents/${agentId}/web-chat/threads`,
        { schema: ThreadsListSchema },
      );
      return response.data;
    },
    enabled: enabled && !!agentId,
  });

  const renameThread = useMutation({
    mutationFn: async ({ threadId, title }: { threadId: string; title: string }) => {
      const response = await api.patch<WebChatThread>(
        `${orgApiBase}/agents/${agentId}/web-chat/threads/${encodeURIComponent(threadId)}`,
        { displayName: title },
        { schema: WebChatThreadSchema },
      );
      return response.data;
    },
    onSuccess: (thread) => {
      queryClient.setQueryData<WebChatThread[]>(queryKey, (current) => {
        const base = current ?? [];
        if (base.some((t) => t.threadId === thread.threadId)) {
          return base.map((t) => (t.threadId === thread.threadId ? thread : t));
        }
        return [...base, thread];
      });
    },
  });

  const deleteThread = useMutation({
    mutationFn: async (threadId: string) => {
      await api.delete(
        `${orgApiBase}/agents/${agentId}/web-chat/threads/${encodeURIComponent(threadId)}`,
      );
      return threadId;
    },
    onSuccess: (threadId) => {
      queryClient.setQueryData<WebChatThread[]>(queryKey, (current) =>
        (current ?? []).filter((t) => t.threadId !== threadId),
      );
    },
  });

  return {
    threads: query.data ?? [],
    isLoading: query.isPending,
    refetch: query.refetch,
    renameThread: (threadId: string, title: string) =>
      renameThread.mutateAsync({ threadId, title }),
    deleteThread: (threadId: string) => deleteThread.mutateAsync(threadId),
  };
}
