"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";
import { api } from "@/shared/api";
import { createQueryKeyStructure } from "@/shared/query-keys";

import {
  CommunicationConnectionSchema,
  CommunicationDiagnosticsSchema,
  PaginatedCommunicationJournalEntriesSchema,
  CommunicationReconnectSchema,
  CommunicationRetrySchema,
  CommunicationPlatformSchema,
  type CommunicationConnection,
  type CommunicationPlatform,
  type CommunicationDiagnostics,
  type CommunicationJournalKind,
  type PaginatedCommunicationJournalEntries,
  type CommunicationReconnect,
  type CommunicationRetry,
  type CreateCommunicationConnection,
  type UpdateCommunicationConnection,
} from "../schemas";

export const communicationConnectionsKey = createQueryKeyStructure("communication-connections");
export const communicationPlatformsKey = createQueryKeyStructure("communication-platforms");
export const communicationDiagnosticsKey = createQueryKeyStructure("communication-connection-diagnostics");
export const communicationJournalKey = createQueryKeyStructure("communication-connection-journal");

const JOURNAL_PAGE_SIZE = 20;

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
        `${orgApiBase}/agents/${agentId}/connections/${connectionId}/summary`,
        { schema: CommunicationDiagnosticsSchema },
      );
      return response.data;
    },
    enabled: enabled && Boolean(agentId && connectionId),
  });
}

export function useCommunicationConnectionJournal(agentId: string, connectionId: string, kind: CommunicationJournalKind) {
  const orgApiBase = useOrganizationApiBase();
  const { selectedOrganization } = useOrganizationContext();
  const organizationId = selectedOrganization?.id ?? "";
  const query = useInfiniteQuery({
    queryKey: communicationJournalKey.list({ organizationId, agentId, connectionId, kind }),
    queryFn: async ({ pageParam }) => {
      const params = new URLSearchParams({
        page: String(pageParam),
        page_size: String(JOURNAL_PAGE_SIZE),
        kind,
      });
      const response = await api.get<PaginatedCommunicationJournalEntries>(
        `${orgApiBase}/agents/${agentId}/connections/${connectionId}/journal?${params.toString()}`,
        { schema: PaginatedCommunicationJournalEntriesSchema },
      );
      return response.data;
    },
    initialPageParam: 1,
    getNextPageParam: (lastPage) => {
      const nextPage = lastPage.page + 1;
      return nextPage <= Math.ceil(lastPage.total / lastPage.pageSize) ? nextPage : undefined;
    },
    enabled: Boolean(agentId && connectionId),
  });
  // Offset pages can overlap when a new journal record arrives between requests.
  // Keep the append-only record ID canonical so a live refresh never renders a row twice.
  const entries = Array.from(
    new Map((query.data?.pages.flatMap((page) => page.items) ?? []).map((entry) => [entry.id, entry])).values(),
  );
  return {
    entries,
    total: query.data?.pages[0]?.total ?? 0,
    isLoading: query.isPending,
    isFetchingNextPage: query.isFetchingNextPage,
    isFetchingNextPageError: query.isFetchNextPageError,
    hasNextPage: query.hasNextPage,
    fetchNextPage: query.fetchNextPage,
    error: query.error,
    refetch: query.refetch,
  };
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
    for (const kind of ["delivery", "connection"] as const) {
      void queryClient.invalidateQueries({
        queryKey: communicationJournalKey.list({ organizationId, agentId, connectionId, kind }),
      });
    }
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
