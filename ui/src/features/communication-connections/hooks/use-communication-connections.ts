"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";
import { api } from "@/shared/api";
import { createQueryKeyStructure } from "@/shared/query-keys";

import {
  CommunicationConnectionSchema,
  CommunicationPlatformSchema,
  type CommunicationConnection,
  type CommunicationPlatform,
  type CreateCommunicationConnection,
  type UpdateCommunicationConnection,
} from "../schemas";

export const communicationConnectionsKey = createQueryKeyStructure("communication-connections");
export const communicationPlatformsKey = createQueryKeyStructure("communication-platforms");

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

  return { createConnection, updateConnection, retireConnection };
}
