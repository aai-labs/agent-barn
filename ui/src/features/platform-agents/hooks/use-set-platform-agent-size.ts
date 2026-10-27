"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { PlatformAgentSchema, type PlatformAgent } from "../schemas";
import { platformAgentsKey } from "../utils";

/**
 * Override one Agent's size, locking it for its Organization, or null to clear the override.
 * Never restarts the Agent: a running one reports `pendingSize` until its next start.
 */
export function useSetPlatformAgentSize() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ agentId, agentSizeId }: { agentId: string; agentSizeId: string | null }) =>
      (
        await api.put<PlatformAgent>(
          `/api/v1/platform/agents/${agentId}/agent-size`,
          { agentSizeId },
          { schema: PlatformAgentSchema },
        )
      ).data,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: platformAgentsKey.all }),
  });
}
