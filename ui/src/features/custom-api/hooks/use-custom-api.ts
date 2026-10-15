"use client";

import { useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { agentsKey } from "@/features/agents/utils";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";
import { api } from "@/shared/api";
import { createQueryKeyStructure } from "@/shared/query-keys";

import {
  CustomApiConnectionSchema,
  type CustomApiConnection,
  type CustomApiWrite,
  type CustomApiBatch,
} from "../schemas";

export const customApiKey = createQueryKeyStructure("custom-api-connections");
export function useCustomApi(agentId: string, running: boolean) {
  const base = useOrganizationApiBase();
  const organizationId =
    useOrganizationContext().selectedOrganization?.id ?? "";
  const queryClient = useQueryClient();
  const url = `${base}/agents/${agentId}/custom-api-connections`;
  const polling = useRef<{ scope: string; startedAt: number } | null>(null);
  const queryKey = customApiKey.list({ organizationId, agentId, running });
  const query = useQuery({
    queryKey,
    enabled: Boolean(agentId && organizationId),
    queryFn: async () => {
      const previous =
        queryClient.getQueryData<CustomApiConnection[]>(queryKey);
      // Agent detail reads reconcile runtime readiness before connection metadata is read.
      if (running && previous?.some((connection) => connection.pendingApply)) {
        await queryClient.invalidateQueries({
          queryKey: agentsKey.detail(agentId),
        });
      }
      return (
        await api.get<CustomApiConnection[]>(url, {
          schema: z.array(CustomApiConnectionSchema),
        })
      ).data;
    },
    refetchInterval: (query) => {
      if (
        !running ||
        !query.state.data?.some((connection) => connection.pendingApply)
      ) {
        polling.current = null;
        return false;
      }
      const scope = `${organizationId}:${agentId}`;
      if (polling.current?.scope !== scope)
        polling.current = { scope, startedAt: Date.now() };
      return Date.now() - polling.current.startedAt < 180_000 ? 5_000 : false;
    },
  });
  const mutation = useMutation({
    mutationFn: async (action: {
      id?: string;
      data?: CustomApiWrite;
      remove?: boolean;
      restart?: boolean;
    }) => {
      if (action.remove)
        return api.delete(
          `${url}/${action.id}${action.restart ? "?restart=true" : ""}`,
          { timeout: 120_000 },
        );
      if (action.id && action.restart === undefined)
        return api.patch(`${url}/${action.id}`, action.data, {
          schema: CustomApiConnectionSchema,
        });
      if (action.id)
        return api.post(
          `${url}/${action.id}/apply`,
          { ...action.data, restart: action.restart ?? false },
          { schema: CustomApiConnectionSchema, timeout: 120_000 },
        );
      return api.post(
        url,
        { ...action.data, ...(action.restart ? { restart: true } : {}) },
        { schema: CustomApiConnectionSchema, timeout: 120_000 },
      );
    },
    onMutate: () => {
      polling.current = null;
    },
    onSettled: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: customApiKey.all }),
        queryClient.invalidateQueries({ queryKey: agentsKey.detail(agentId) }),
        queryClient.invalidateQueries({ queryKey: agentsKey.lists() }),
        queryClient.invalidateQueries({ queryKey: agentsKey.health(agentId) }),
      ]);
    },
  });
  const batchMutation = useMutation({
    mutationFn: (data: CustomApiBatch) => api.post(`${url}/apply`, data, {
      schema: z.array(CustomApiConnectionSchema), timeout: 120_000,
    }),
    onMutate: () => { polling.current = null; },
    onSettled: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: customApiKey.all }),
        queryClient.invalidateQueries({ queryKey: agentsKey.detail(agentId) }),
        queryClient.invalidateQueries({ queryKey: agentsKey.lists() }),
        queryClient.invalidateQueries({ queryKey: agentsKey.health(agentId) }),
      ]);
    },
  });
  return {
    connections: query.data,
    isLoadingConnections: query.isLoading,
    connectionsError: query.error,
    refetchConnections: query.refetch,
    connectionMutation: mutation,
    batchMutation,
    preflight: (data: CustomApiBatch) => api.post(`${url}/preflight`, data, { timeout: 120_000 }),
  };
}
