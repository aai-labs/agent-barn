"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { agentsKey } from "@/features/agents/utils";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { api } from "@/shared/api";

import {
  type AgentAddon,
  type AgentAddonRequest,
  type AgentAddons,
  AgentAddonSchema,
  AgentAddonsSchema,
} from "../schemas";
import { agentAddonsKey } from "../utils";

/** One Agent's add-ons, newest first, and the kinds its runtime offers. Owners and Admins only. */
export function useAgentAddons(agentId: string, enabled = true) {
  const orgApiBase = useOrganizationApiBase();
  const query = useQuery({
    queryKey: agentAddonsKey.list(agentId),
    queryFn: async () =>
      (await api.get<AgentAddons>(`${orgApiBase}/agents/${agentId}/addons`, { schema: AgentAddonsSchema })).data,
    enabled: enabled && Boolean(agentId),
  });

  return {
    addons: query.data?.items ?? [],
    availableKinds: query.data?.availableKinds ?? [],
    maxActive: query.data?.maxActive ?? 0,
    isLoadingAddons: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}

function useInvalidateAgentAddons(agentId: string) {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: agentAddonsKey.list(agentId) });
    // `pendingAddons` on the Agent moves only with a decision, but a withdrawal can free a place.
    void queryClient.invalidateQueries({ queryKey: agentsKey.detail(agentId), exact: true });
  };
}

/** Ask a Platform Administrator to approve an add-on for this Agent. */
export function useRequestAgentAddon(agentId: string) {
  const orgApiBase = useOrganizationApiBase();
  const invalidate = useInvalidateAgentAddons(agentId);
  return useMutation({
    mutationFn: async (request: AgentAddonRequest) =>
      (await api.post<AgentAddon>(`${orgApiBase}/agents/${agentId}/addons`, request, { schema: AgentAddonSchema }))
        .data,
    onSuccess: invalidate,
  });
}

/** Withdraw a Pending request. */
export function useWithdrawAgentAddon(agentId: string) {
  const orgApiBase = useOrganizationApiBase();
  const invalidate = useInvalidateAgentAddons(agentId);
  return useMutation({
    mutationFn: async (addonId: string) =>
      (
        await api.post<AgentAddon>(`${orgApiBase}/agents/${agentId}/addons/${addonId}/withdraw`, undefined, {
          schema: AgentAddonSchema,
        })
      ).data,
    onSuccess: invalidate,
  });
}
