"use client";

import { useQuery } from "@tanstack/react-query";
import { z } from "zod";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import { SlackUser, SlackUserSchema } from "../schemas";
import { agentsKey } from "../utils";

export function useSlackUsers(agentId: string | undefined) {
  const orgApiBase = useOrganizationApiBase();
  const query = useQuery({
    queryKey: agentsKey.slackUsers(agentId ?? ""),
    queryFn: async () => {
      const response = await api.get<SlackUser[]>(
        `${orgApiBase}/agents/${agentId}/slack/users`,
        { schema: z.array(SlackUserSchema) },
      );
      return response.data;
    },
    enabled: !!agentId,
    staleTime: 60_000,
  });

  return {
    users: query.data ?? [],
    isLoading: query.isPending,
    error: query.error,
  };
}
