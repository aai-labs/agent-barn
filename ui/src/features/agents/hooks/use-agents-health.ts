"use client";

import { skipToken, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import { AgentHealthSchema, type AgentHealth } from "../schemas";
import { agentsKey } from "../utils";

const AgentHealthItemsSchema = z.array(AgentHealthSchema.extend({ agentId: z.string().uuid() }));

/**
 * The health of every Agent a list page shows, in one request per poll instead of one
 * per Agent. Each answer lands in that Agent's own health cache, which the list's cards
 * and rows read with `useListedAgentHealth` (and the path bar with its cached read).
 * Pass only the Agents whose health the viewer may read: running, with `activity.read`.
 */
export function useAgentsHealth(agentIds: string[], refetchIntervalMs: number) {
  const orgApiBase = useOrganizationApiBase();
  const queryClient = useQueryClient();
  const ids = [...agentIds].sort();

  useQuery({
    queryKey: [...agentsKey.all, "health-batch", orgApiBase, ids],
    queryFn: async () => {
      // One agent_ids parameter per Agent, as the API reads a list.
      const query = new URLSearchParams(ids.map((id) => ["agent_ids", id]));
      let response;
      try {
        response = await api.get<z.infer<typeof AgentHealthItemsSchema>>(
          `${orgApiBase}/agents/health?${query.toString()}`,
          { schema: AgentHealthItemsSchema },
        );
      } catch (error) {
        // Unknown now, rather than the last answer: each Agent reads as an error, as a
        // failed request of its own used to.
        for (const id of ids) queryClient.setQueryData<AgentHealth>(agentsKey.health(id), { status: "error" });
        throw error;
      }
      for (const { agentId, ...health } of response.data) {
        queryClient.setQueryData<AgentHealth>(agentsKey.health(agentId), health);
      }
      return response.data;
    },
    enabled: ids.length > 0,
    refetchInterval: refetchIntervalMs,
    retry: false,
  });
}

/** An Agent's health as its list's `useAgentsHealth` batch last read it; it never fetches. */
export function useListedAgentHealth(agentId: string, enabled: boolean): AgentHealth | null {
  const query = useQuery<AgentHealth>({ queryKey: agentsKey.health(agentId), queryFn: skipToken });
  return enabled ? (query.data ?? null) : null;
}
