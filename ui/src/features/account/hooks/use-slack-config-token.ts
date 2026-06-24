"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { slackConfigTokenKey } from "@/shared/query-keys";

import {
  SlackConfigTokenReadSchema,
  type SlackConfigTokenRead,
} from "../schemas";

export function useSlackConfigToken() {
  const query = useQuery({
    queryKey: slackConfigTokenKey.detail("me"),
    queryFn: async () => {
      const response = await api.get<SlackConfigTokenRead>(
        "/api/v1/auth/me/slack-config-token",
        { schema: SlackConfigTokenReadSchema },
      );
      return response.data;
    },
  });

  return {
    hasToken: query.data?.hasToken ?? false,
    tokenPreview: query.data?.tokenPreview ?? null,
    isLoading: query.isPending,
    error: query.error,
  };
}
