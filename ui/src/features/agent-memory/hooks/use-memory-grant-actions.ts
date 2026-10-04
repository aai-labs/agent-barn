"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { api } from "@/shared/api";

import { MemoryGrantSchema, type MemoryGrant } from "../schemas";
import { memoryGrantsKey } from "../utils";

export type CreateMemoryGrantInput = {
  agentId: string;
  /** Omit for an Organization Memory grant. */
  sourceAgentId?: string;
  access: "read" | "read_write";
};

export function useCreateMemoryGrant() {
  const queryClient = useQueryClient();
  const orgApiBase = useOrganizationApiBase();

  return useMutation({
    mutationFn: async ({ agentId, sourceAgentId, access }: CreateMemoryGrantInput) => {
      const response = await api.post<MemoryGrant>(
        `${orgApiBase}/memory-grants`,
        { agentId, sourceAgentId: sourceAgentId ?? null, access },
        { schema: MemoryGrantSchema },
      );
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: memoryGrantsKey.forOrganization(orgApiBase) });
    },
  });
}

export function useRevokeMemoryGrant() {
  const queryClient = useQueryClient();
  const orgApiBase = useOrganizationApiBase();

  return useMutation({
    mutationFn: async (grantId: string) => {
      await api.delete(`${orgApiBase}/memory-grants/${grantId}`);
    },
    // A grant that is already gone (404) leaves the list stale as well as a success does.
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: memoryGrantsKey.forOrganization(orgApiBase) });
    },
  });
}
