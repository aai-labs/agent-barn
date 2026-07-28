"use client";

import { useMutation } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

export type PairAgentData = {
  agentId: string;
  platform: string;
  code: string;
};

export function usePairAgent() {
  const orgApiBase = useOrganizationApiBase();
  return useMutation({
    mutationFn: async ({ agentId, platform, code }: PairAgentData) => {
      const response = await api.post<{ message: string }>(
        `${orgApiBase}/agents/${agentId}/pair`,
        { platform, code },
      );
      return response.data;
    },
  });
}
