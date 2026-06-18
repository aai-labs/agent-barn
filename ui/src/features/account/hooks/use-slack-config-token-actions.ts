"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { slackConfigTokenKey } from "@/shared/query-keys";

import {
  SlackConfigTokenReadSchema,
  type SlackConfigTokenRead,
} from "../schemas";

export function useSlackConfigTokenActions() {
  const queryClient = useQueryClient();

  const saveToken = useMutation({
    mutationFn: async (token: string) => {
      const response = await api.put<SlackConfigTokenRead>(
        "/api/v1/auth/me/slack-config-token",
        { token },
        { schema: SlackConfigTokenReadSchema },
      );
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: slackConfigTokenKey.all });
    },
  });

  const deleteToken = useMutation({
    mutationFn: async () => {
      await api.delete("/api/v1/auth/me/slack-config-token");
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: slackConfigTokenKey.all });
    },
  });

  return { saveToken, deleteToken };
}
