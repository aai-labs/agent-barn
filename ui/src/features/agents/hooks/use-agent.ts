"use client";

import { useCallback, useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import { Agent, AgentSchema } from "../schemas";
import { agentsKey } from "../utils";

/**
 * While a managed update is in flight, the detail query keeps polling: the
 * server's own state tells the banner's story (hidden mid-flow, gone on
 * success, back after a rollback) — but only if the cache keeps looking.
 * The query itself neither polls nor refetches on focus, so without this the
 * banner would freeze on whatever was true the moment Update was clicked.
 */
const UPDATE_POLL_INTERVAL_MS = 5_000;
// Hard cap: a flow that outlives this (hung backend) stops polling and falls
// back to today's behaviour — a stale banner until the next reload.
const UPDATE_POLL_MAX_MS = 10 * 60 * 1000;

const RESTORE_POINT_BUSY = new Set(["PENDING", "CAPTURING", "RESTORING", "DELETING"]);

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
    refetchInterval: () =>
      queryClient.getQueryData(agentsKey.updateInFlight(agentId)) ? UPDATE_POLL_INTERVAL_MS : false,
  });

  const agent = query.data;
  // RUNNING -> STOPPED is how every flow begins; only a return to RUNNING (or
  // a terminal failure) after that proves the flow resolved, so the first
  // post-click RUNNING read is never mistaken for "done".
  const sawBusyRef = useRef(false);

  useEffect(() => {
    if (!agentId || !agent) return;
    const inFlight = queryClient.getQueryData<{ startedAt: number }>(agentsKey.updateInFlight(agentId));
    if (!inFlight) {
      sawBusyRef.current = false;
      return;
    }
    if (Date.now() - inFlight.startedAt > UPDATE_POLL_MAX_MS) {
      queryClient.removeQueries({ queryKey: agentsKey.updateInFlight(agentId) });
      return;
    }

    if (agent.status !== "RUNNING") {
      sawBusyRef.current = true;
      // A capture failure or a failed rollback ends the flow without ever
      // returning to RUNNING. The restore-point rows (or the recorded error)
      // say so; with no rows visible yet the cache is undecided — keep asking.
      const points = queryClient.getQueryData(agentsKey.restorePoints(agentId)) as
        | { pages?: { items: { status: string }[] }[] }
        | undefined;
      const busyRows = points?.pages?.some((page) => page.items.some((item) => RESTORE_POINT_BUSY.has(item.status)));
      if (agent.lastError || busyRows === false) {
        queryClient.removeQueries({ queryKey: agentsKey.updateInFlight(agentId) });
        void queryClient.invalidateQueries({ queryKey: agentsKey.restorePoints(agentId) });
      }
      return;
    }
    if (sawBusyRef.current) {
      queryClient.removeQueries({ queryKey: agentsKey.updateInFlight(agentId) });
      void queryClient.invalidateQueries({ queryKey: agentsKey.restorePoints(agentId) });
    }
  }, [agent, agentId, queryClient]);

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
