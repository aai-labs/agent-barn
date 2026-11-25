"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { agentsKey } from "@/features/agents/utils";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";
import { api } from "@/shared/api";

import { AgentMcpServersSchema, type AgentMcpCredentialWrite, type AgentMcpServers } from "../schemas";
import { mcpServersKey } from "../utils";

/** The MCP servers as they stand for one Agent (the Organization's and its own), and saving its attachments. */
export function useAgentMcpServers(agentId: string) {
  const base = useOrganizationApiBase();
  const organizationId = useOrganizationContext().selectedOrganization?.id ?? "";
  const queryClient = useQueryClient();
  const url = `${base}/agents/${agentId}/mcp-servers`;
  const queryKey = mcpServersKey.list({ organizationId, agentId });
  const query = useQuery({
    queryKey,
    enabled: Boolean(agentId && organizationId),
    queryFn: async () => (await api.get<AgentMcpServers>(url, { schema: AgentMcpServersSchema })).data,
  });
  const save = useMutation({
    mutationFn: async (body: { attachedServerIds: string[]; restart: boolean }) =>
      // A restart stops and starts the Agent before answering.
      (
        await api.put<AgentMcpServers>(url, body, {
          schema: AgentMcpServersSchema,
          timeout: 180_000,
        })
      ).data,
    onSuccess: (data, body) => {
      queryClient.setQueryData(queryKey, data);
      void queryClient.invalidateQueries({ queryKey: mcpServersKey.all });
      if (body.restart) void queryClient.invalidateQueries({ queryKey: agentsKey.all });
    },
  });
  const setCredential = useMutation({
    // The API checks the credential against the live server first.
    mutationFn: async ({ serverId, data }: { serverId: string; data: AgentMcpCredentialWrite }) =>
      (
        await api.put<AgentMcpServers>(`${url}/${serverId}/credential`, data, {
          schema: AgentMcpServersSchema,
          timeout: 60_000,
        })
      ).data,
    onSuccess: (data) => queryClient.setQueryData(queryKey, data),
  });
  const removeCredential = useMutation({
    mutationFn: async (serverId: string) => {
      await api.delete(`${url}/${serverId}/credential`);
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey }),
  });
  return {
    servers: query.data?.servers ?? [],
    agentServers: query.data?.agentServers ?? [],
    canManageRestricted: query.data?.canManageRestricted ?? false,
    pendingRestart: query.data?.pendingRestart ?? false,
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
    save: save.mutateAsync,
    isSaving: save.isPending,
    setCredential,
    removeCredential,
  };
}
