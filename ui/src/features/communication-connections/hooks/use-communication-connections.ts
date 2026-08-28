"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";
import { api } from "@/shared/api";
import { createQueryKeyStructure } from "@/shared/query-keys";

import {
  CommunicationConnectionSchema,
  CommunicationDiagnosticsSchema,
  CommunicationReconnectSchema,
  CommunicationRetrySchema,
  CommunicationPlatformSchema,
  type CommunicationConnection,
  type CommunicationPlatform,
  type CommunicationDiagnostics,
  type CommunicationReconnect,
  type CommunicationRetry,
  type CreateCommunicationConnection,
  type UpdateCommunicationConnection,
} from "../schemas";

export const communicationConnectionsKey = createQueryKeyStructure("communication-connections");
export const communicationPlatformsKey = createQueryKeyStructure("communication-platforms");
export const communicationDiagnosticsKey = createQueryKeyStructure("communication-connection-diagnostics");

export function useCommunicationPlatforms() {
  const orgApiBase = useOrganizationApiBase();
  const { selectedOrganization } = useOrganizationContext();
  const organizationId = selectedOrganization?.id ?? "";
  return useQuery({
    queryKey: communicationPlatformsKey.list({ organizationId }),
    queryFn: async () => {
      const response = await api.get<CommunicationPlatform[]>(
        `${orgApiBase}/communication-platforms`,
        { schema: z.array(CommunicationPlatformSchema) },
      );
      return response.data;
    },
  });
}

export function useCommunicationConnections(agentId: string) {
  const orgApiBase = useOrganizationApiBase();
  const { selectedOrganization } = useOrganizationContext();
  const organizationId = selectedOrganization?.id ?? "";
  return useQuery({
    queryKey: communicationConnectionsKey.list({ organizationId, agentId }),
    queryFn: async () => {
      const response = await api.get<CommunicationConnection[]>(
        `${orgApiBase}/agents/${agentId}/connections`,
        { schema: z.array(CommunicationConnectionSchema) },
      );
      return response.data;
    },
    enabled: Boolean(agentId),
  });
}

export function useCommunicationConnectionDiagnostics(
  agentId: string,
  connectionId: string,
  enabled = true,
) {
  const orgApiBase = useOrganizationApiBase();
  const { selectedOrganization } = useOrganizationContext();
  const organizationId = selectedOrganization?.id ?? "";
  return useQuery({
    queryKey: communicationDiagnosticsKey.detail(`${organizationId}:${connectionId}`),
    queryFn: async () => {
      const response = await api.get<CommunicationDiagnostics>(
        `${orgApiBase}/agents/${agentId}/connections/${connectionId}/diagnostics`,
        { schema: CommunicationDiagnosticsSchema },
      );
      return response.data;
    },
    enabled: enabled && Boolean(agentId && connectionId),
  });
}

export function useDownloadAppPackage() {
  const orgApiBase = useOrganizationApiBase();

  return async function downloadAppPackage(agentId: string, connectionId: string, fallbackName: string) {
    const response = await api.getFile(`${orgApiBase}/agents/${agentId}/connections/${connectionId}/app-package`);
    const filename =
      /filename="([^"]+)"/.exec(response.headers?.["content-disposition"] ?? "")?.[1] ?? `${fallbackName}.zip`;
    const objectUrl = URL.createObjectURL(response.data);
    try {
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = filename;
      link.click();
    } finally {
      URL.revokeObjectURL(objectUrl);
    }
  };
}

export function useCommunicationConnectionActions() {
  const orgApiBase = useOrganizationApiBase();
  const { selectedOrganization } = useOrganizationContext();
  const organizationId = selectedOrganization?.id ?? "";
  const queryClient = useQueryClient();

  function invalidate(agentId: string) {
    return queryClient.invalidateQueries({
      queryKey: communicationConnectionsKey.list({ organizationId, agentId }),
    });
  }

  function invalidateDiagnostics(agentId: string, connectionId: string) {
    void queryClient.invalidateQueries({
      queryKey: communicationDiagnosticsKey.detail(`${organizationId}:${connectionId}`),
    });
    return invalidate(agentId);
  }

  const createConnection = useMutation({
    mutationFn: async ({ agentId, ...data }: CreateCommunicationConnection) => {
      const response = await api.post<CommunicationConnection>(
        `${orgApiBase}/agents/${agentId}/connections`,
        data,
        { schema: CommunicationConnectionSchema },
      );
      return response.data;
    },
    onSuccess: (connection) => invalidate(connection.agentId),
  });

  const updateConnection = useMutation({
    mutationFn: async ({ agentId, connectionId, ...data }: UpdateCommunicationConnection) => {
      const response = await api.patch<CommunicationConnection>(
        `${orgApiBase}/agents/${agentId}/connections/${connectionId}`,
        data,
        { schema: CommunicationConnectionSchema },
      );
      return response.data;
    },
    onSuccess: (connection) => invalidate(connection.agentId),
  });

  const retireConnection = useMutation({
    mutationFn: async ({ agentId, connectionId, revision }: Pick<UpdateCommunicationConnection, "agentId" | "connectionId" | "revision">) => {
      await api.delete(
        `${orgApiBase}/agents/${agentId}/connections/${connectionId}?revision=${revision}`,
      );
      return agentId;
    },
    onSuccess: invalidate,
  });

  const reconnectConnection = useMutation({
    mutationFn: async ({ agentId, connectionId }: { agentId: string; connectionId: string }) => {
      const response = await api.post<CommunicationReconnect>(
        `${orgApiBase}/agents/${agentId}/connections/${connectionId}/reconnect`,
        undefined,
        { schema: CommunicationReconnectSchema },
      );
      return response.data;
    },
    onSuccess: (data) => invalidateDiagnostics(data.connection.agentId, data.connection.id),
  });

  const retryDelivery = useMutation({
    mutationFn: async ({ agentId, connectionId, deliveryId }: { agentId: string; connectionId: string; deliveryId: string }) => {
      const response = await api.post<CommunicationRetry>(
        `${orgApiBase}/agents/${agentId}/connections/${connectionId}/deliveries/${deliveryId}/retry`,
        undefined,
        { schema: CommunicationRetrySchema },
      );
      return response.data;
    },
    onSuccess: (_data, variables) => invalidateDiagnostics(variables.agentId, variables.connectionId),
  });

  return { createConnection, updateConnection, retireConnection, reconnectConnection, retryDelivery };
}
