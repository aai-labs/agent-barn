"use client";

import { useQuery } from "@tanstack/react-query";
import { z } from "zod";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import { WebChatThreadSchema, type WebChatThread } from "../schemas";
import { agentsKey } from "../utils";

const ThreadsListSchema = z.array(WebChatThreadSchema);

export function useWebChatThreads(agentId: string, enabled: boolean) {
  const orgApiBase = useOrganizationApiBase();

  const query = useQuery({
    queryKey: agentsKey.webChatThreads(agentId),
    queryFn: async () => {
      const response = await api.get<WebChatThread[]>(
        `${orgApiBase}/agents/${agentId}/web-chat/threads`,
        { schema: ThreadsListSchema },
      );
      return response.data;
    },
    enabled: enabled && !!agentId,
  });

  return {
    threads: query.data ?? [],
    isLoading: query.isPending,
    refetch: query.refetch,
  };
}
