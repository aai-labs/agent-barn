"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import { agentsKey } from "../utils";

export function useDeleteAgent() {
  const queryClient = useQueryClient();
  const orgApiBase = useOrganizationApiBase();

  return useMutation({
    mutationFn: async (agentId: string) => {
      await api.delete(`${orgApiBase}/agents/${agentId}`);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: agentsKey.lists() });
    },
  });
}
