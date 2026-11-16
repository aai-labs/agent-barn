"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";
import { api } from "@/shared/api";

import {
  McpServerProbeSchema,
  McpServerSchema,
  type McpServer,
  type McpServerProbe,
  type McpServerWrite,
} from "../schemas";
import { mcpServersKey } from "../utils";

export function useMcpServers() {
  const base = useOrganizationApiBase();
  const organizationId = useOrganizationContext().selectedOrganization?.id ?? "";
  const query = useQuery({
    queryKey: mcpServersKey.list({ organizationId }),
    enabled: Boolean(organizationId),
    queryFn: async () =>
      (
        await api.get<McpServer[]>(`${base}/mcp-servers`, {
          schema: z.array(McpServerSchema),
        })
      ).data,
  });
  return {
    servers: query.data ?? [],
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}

/** An Organization server's path, or with `agentId` that Agent's own servers. */
function serversPath(base: string, agentId?: string): string {
  return agentId ? `${base}/agents/${agentId}/mcp-servers` : `${base}/mcp-servers`;
}

function useInvalidateMcpServers() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: mcpServersKey.all });
}

export function useSaveMcpServer(agentId?: string) {
  const base = useOrganizationApiBase();
  const invalidate = useInvalidateMcpServers();
  const path = serversPath(base, agentId);
  return useMutation({
    mutationFn: async ({ id, data }: { id?: string; data: McpServerWrite }) => {
      // Saving connects to the server once, so allow for a slow upstream.
      const response = id
        ? await api.patch<McpServer>(`${path}/${id}`, data, {
            schema: McpServerSchema,
            timeout: 60_000,
          })
        : await api.post<McpServer>(path, data, {
            schema: McpServerSchema,
            timeout: 60_000,
          });
      return response.data;
    },
    onSuccess: () => void invalidate(),
  });
}

/** Deletes an Organization server, or an Agent server through its Agent (`agentId`). */
export function useDeleteMcpServer() {
  const base = useOrganizationApiBase();
  const invalidate = useInvalidateMcpServers();
  return useMutation({
    mutationFn: async ({ id, agentId }: { id: string; agentId?: string | null }) => {
      await api.delete(`${serversPath(base, agentId ?? undefined)}/${id}`);
    },
    onSuccess: () => void invalidate(),
  });
}

/** Connects to a server without saving it: an unsaved draft, or a saved server with draft changes. */
export function useProbeMcpServer(agentId?: string) {
  const base = useOrganizationApiBase();
  const path = serversPath(base, agentId);
  return useMutation({
    mutationFn: async ({ id, data }: { id?: string; data: McpServerWrite }) => {
      const url = id ? `${path}/${id}/probe` : `${path}/probe`;
      const body = id
        ? data
        : {
            name: data.name,
            url: data.url,
            auth: data.auth,
            headers: data.headers,
          };
      return (
        await api.post<McpServerProbe>(url, body, {
          schema: McpServerProbeSchema,
          timeout: 60_000,
        })
      ).data;
    },
  });
}
