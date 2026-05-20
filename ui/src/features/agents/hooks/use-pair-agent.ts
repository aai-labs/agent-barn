"use client";

import { useMutation } from "@tanstack/react-query";

import { api } from "@/shared/api";

export type PairAgentData = {
  agentId: string;
  platform: string;
  code: string;
};

export function usePairAgent() {
  return useMutation({
    mutationFn: async ({ agentId, platform, code }: PairAgentData) => {
      const response = await api.post<{ message: string }>(
        `/api/v1/agents/${agentId}/pair`,
        { platform, code },
      );
      return response.data;
    },
  });
}
