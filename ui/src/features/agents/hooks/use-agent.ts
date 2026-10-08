"use client";

import { useCallback, useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import { Agent, AgentSchema } from "../schemas";
import { agentsKey } from "../utils";

/**
 * While a managed update runs, the detail query polls: the server's own
 * `updateInProgress` flag says when it has ended, and its status and
 * `lastManagedUpdate` say how. The query otherwise neither polls nor refetches
 * on focus, so without this the page would freeze on the 202's snapshot. The
 * server drops the flag by itself if the process running the update dies, so
 * this never polls forever.
 */
const UPDATE_POLL_INTERVAL_MS = 5_000;

export function useAgent(agentId: string) {
  const orgApiBase = useOrganizationApiBase();
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: agentsKey.detail(agentId),
    queryFn: async () => {
      const response = await api.get<Agent>(`${orgApiBase}/agents/${agentId}`, {
        schema: AgentSchema,
      });
      return response.data;
    },
    enabled: !!agentId,
    refetchInterval: (current) => (current.state.data?.updateInProgress ? UPDATE_POLL_INTERVAL_MS : false),
  });

  // When an update ends, the restore points, the list card and the health
  // read it touched are stale too.
  const updateInProgress = query.data?.updateInProgress ?? false;
  const wasInProgressRef = useRef(updateInProgress);
  useEffect(() => {
    if (wasInProgressRef.current && !updateInProgress) {
      void queryClient.invalidateQueries({ queryKey: agentsKey.restorePoints(agentId) });
      void queryClient.invalidateQueries({ queryKey: agentsKey.health(agentId) });
      void queryClient.invalidateQueries({ queryKey: agentsKey.lists() });
    }
    wasInProgressRef.current = updateInProgress;
  }, [agentId, queryClient, updateInProgress]);

  return {
    agent: query.data,
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}

/**
 * Reads the Agent now rather than from cache. The detail query neither polls nor
 * refetches on focus, so anything sending the Agent's own state back to the server
 * must build that request from a current read or be rejected as stale.
 */
export function useFetchAgent() {
  const queryClient = useQueryClient();
  const orgApiBase = useOrganizationApiBase();

  return useCallback(
    async (agentId: string) => {
      const response = await api.get<Agent>(`${orgApiBase}/agents/${agentId}`, {
        schema: AgentSchema,
      });
      queryClient.setQueryData(agentsKey.detail(agentId), response.data);
      return response.data;
    },
    [orgApiBase, queryClient],
  );
}
