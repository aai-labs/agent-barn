"use client";

import { useQuery } from "@tanstack/react-query";
import { z } from "zod";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import { SlackChannel, SlackChannelSchema } from "../schemas";
import { agentsKey } from "../utils";

export function useSlackChannels(agentId: string | undefined) {
  const orgApiBase = useOrganizationApiBase();
  const query = useQuery({
    queryKey: agentsKey.slackChannels(agentId ?? ""),
    queryFn: async () => {
      const response = await api.get<SlackChannel[]>(
        `${orgApiBase}/agents/${agentId}/slack/channels`,
        { schema: z.array(SlackChannelSchema) },
      );
      return response.data;
    },
    enabled: !!agentId,
    staleTime: 60_000,
  });

  return {
    channels: query.data ?? [],
    isLoading: query.isPending,
    error: query.error,
  };
}
