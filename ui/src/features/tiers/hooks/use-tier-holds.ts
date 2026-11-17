"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { agentsKey } from "@/features/agents/utils";
import { organizationsKey } from "@/features/organizations/utils";
import { api } from "@/shared/api";

import { type TierHeldItem, type TierHolds, TierHoldsSchema } from "../schemas";

export const tierHoldsKey = (organizationId: string) => ["tier-holds", organizationId] as const;

/** The organization's agents and what its tier has put on hold. Owners and Admins only. */
export function useTierHolds(organizationId: string, enabled: boolean) {
  const query = useQuery({
    queryKey: tierHoldsKey(organizationId),
    queryFn: async () =>
      (await api.get<TierHolds>(`/api/v1/organizations/${organizationId}/tier-holds`, { schema: TierHoldsSchema }))
        .data,
    enabled: enabled && !!organizationId,
  });
  return { holds: query.data ?? null, isLoading: query.isPending, error: query.error, refetch: query.refetch };
}

type Release =
  | { kind: "connection"; item: TierHeldItem }
  | { kind: "webhook"; item: TierHeldItem }
  | { kind: "memory"; item: TierHeldItem };

/** Hold or release an agent, or switch a held connection, webhook or memory back on. */
export function useTierHoldActions(organizationId: string) {
  const queryClient = useQueryClient();
  const base = `/api/v1/organizations/${organizationId}`;
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: tierHoldsKey(organizationId) });
    void queryClient.invalidateQueries({ queryKey: organizationsKey.detail(organizationId) });
    void queryClient.invalidateQueries({ queryKey: agentsKey.all });
  };

  const setAgentHold = useMutation({
    mutationFn: async ({ agentId, hold }: { agentId: string; hold: boolean }) =>
      (
        await api.post<TierHolds>(`${base}/tier-holds/agents/${agentId}/${hold ? "hold" : "release"}`, undefined, {
          schema: TierHoldsSchema,
        })
      ).data,
    onSuccess: (holds) => {
      queryClient.setQueryData(tierHoldsKey(organizationId), holds);
      refresh();
    },
  });

  const reEnable = useMutation({
    mutationFn: async ({ kind, item }: Release) => {
      if (kind === "connection") {
        await api.patch(`${base}/agents/${item.agentId}/connections/${item.id}`, { enabled: true, revision: item.revision });
      } else if (kind === "webhook") {
        await api.patch(`${base}/agents/${item.agentId}/webhooks/${item.id}`, { enabled: true, revision: item.revision });
      } else {
        await api.put(`${base}/agents/${item.agentId}/memory`, { enabled: true });
      }
    },
    onSuccess: refresh,
  });

  return { setAgentHold, reEnable };
}
