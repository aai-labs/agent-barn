"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { PlatformAgentSchema, type PlatformAgent } from "../schemas";
import { platformAgentsKey } from "../utils";

/** Restart any Agent from Platform View, or start one that is not running. Failures are left to the caller. */
export function useRestartPlatformAgent() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (agentId: string) =>
      (
        await api.post<PlatformAgent>(`/api/v1/platform/agents/${agentId}/restart`, undefined, {
          schema: PlatformAgentSchema,
        })
      ).data,
    onSettled: () => void queryClient.invalidateQueries({ queryKey: platformAgentsKey.all }),
  });
}
