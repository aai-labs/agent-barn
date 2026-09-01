"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { z } from "zod";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";
import { api } from "@/shared/api";
import { createQueryKeyStructure } from "@/shared/query-keys";

import {
  CommunicationConnectionSchema,
  CommunicationDirectoryEntrySchema,
  CommunicationDiagnosticsSchema,
  PaginatedCommunicationJournalEntriesSchema,
  CommunicationReconnectSchema,
  CommunicationRetrySchema,
  CommunicationPlatformSchema,
  type CommunicationConnection,
  type CommunicationDirectoryEntry,
  type CommunicationPlatform,
  type CommunicationDiagnostics,
  type CommunicationJournalFilters,
  type CommunicationJournalKind,
  type CommunicationJournalWindow,
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

export function useCommunicationConnectionDirectory(
  agentId: string,
  connectionId: string,
  kind: "guilds" | "channels" | "users" | "roles",
  search = "",
  enabled = true,
  guildId?: string,
) {
  const orgApiBase = useOrganizationApiBase();
  const { selectedOrganization } = useOrganizationContext();
  const organizationId = selectedOrganization?.id ?? "";
  const params = new URLSearchParams();
  if (search.trim()) params.set("search", search.trim());
  if (guildId) params.set("guild_id", guildId);
  return useQuery({
    queryKey: communicationConnectionsKey.detail(`${organizationId}:${connectionId}:directory:${kind}:${guildId ?? ""}:${search.trim()}`),
    queryFn: async () => {
      const response = await api.get<CommunicationDirectoryEntry[]>(
        `${orgApiBase}/agents/${agentId}/connections/${connectionId}/directory/${kind}${params.size ? `?${params}` : ""}`,
        { schema: z.array(CommunicationDirectoryEntrySchema) },
      );
      return response.data;
    },
    enabled: enabled && Boolean(agentId && connectionId),
  });
}

export function useCommunicationConnectionDiagnostics(
  agentId: string,
  connectionId: string,
  enabled = true,
  window: CommunicationJournalWindow = {},
) {
  const orgApiBase = useOrganizationApiBase();
  const { selectedOrganization } = useOrganizationContext();
  const organizationId = selectedOrganization?.id ?? "";
  const searchParams = new URLSearchParams();
  if (window.since) searchParams.set("since", window.since);
  if (window.until) searchParams.set("until", window.until);
  const queryString = searchParams.toString();
  return useQuery({
    queryKey: communicationDiagnosticsKey.detail(
      `${organizationId}:${connectionId}:${window.since ?? ""}:${window.until ?? ""}`,
    ),
    queryFn: async () => {
      const response = await api.get<CommunicationDiagnostics>(
        `${orgApiBase}/agents/${agentId}/connections/${connectionId}/summary${queryString ? `?${queryString}` : ""}`,
        { schema: CommunicationDiagnosticsSchema },
      );
      return response.data;
    },
    enabled: enabled && Boolean(agentId && connectionId),
  });
}

function journalSearchParams(filters: CommunicationJournalFilters): URLSearchParams {
  const params = new URLSearchParams();
  if (filters.since) params.set("since", filters.since);
  if (filters.until) params.set("until", filters.until);
  if (filters.stage) params.set("stage", filters.stage);
  if (filters.failedOnly) params.set("failed_only", "true");
  if (filters.retryableOnly) params.set("retryable_only", "true");
  if (filters.direction) params.set("direction", filters.direction);
  if (filters.deliveryId) params.set("delivery_id", filters.deliveryId);
  if (filters.order) params.set("order", filters.order);
  return params;
}

export function useCommunicationConnectionJournal(
  agentId: string,
  connectionId: string,
  kind: CommunicationJournalKind,
  filters: CommunicationJournalFilters = {},
) {
  const orgApiBase = useOrganizationApiBase();
  const { selectedOrganization } = useOrganizationContext();
  const organizationId = selectedOrganization?.id ?? "";
  const query = useInfiniteQuery({
    queryKey: communicationJournalKey.list({ organizationId, agentId, connectionId, kind, filters }),
    queryFn: async ({ pageParam }) => {
      const params = journalSearchParams(filters);
      params.set("page", String(pageParam));
      params.set("page_size", String(JOURNAL_PAGE_SIZE));
      params.set("kind", kind);
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

/** Every Journal entry for one Delivery, chronological — the lifecycle drill-down. */
export function useCommunicationDeliveryLifecycle(
  agentId: string,
  connectionId: string,
  deliveryId: string | null,
) {
  const orgApiBase = useOrganizationApiBase();
  const { selectedOrganization } = useOrganizationContext();
  const organizationId = selectedOrganization?.id ?? "";
  const query = useInfiniteQuery({
    queryKey: communicationJournalKey.detail(`${organizationId}:${connectionId}:${deliveryId ?? ""}`),
    queryFn: async ({ pageParam }) => {
      const params = journalSearchParams({ deliveryId: deliveryId ?? undefined, order: "asc" });
      params.set("page", String(pageParam));
      params.set("page_size", "100");
      params.set("kind", "delivery");
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
    enabled: Boolean(agentId && connectionId && deliveryId),
  });
  const { fetchNextPage, hasNextPage, isFetchNextPageError, isFetchingNextPage } = query;
  useEffect(() => {
    if (hasNextPage && !isFetchingNextPage && !isFetchNextPageError) {
      void fetchNextPage();
    }
  }, [fetchNextPage, hasNextPage, isFetchNextPageError, isFetchingNextPage]);

  const entries = Array.from(
    new Map((query.data?.pages.flatMap((page) => page.items) ?? []).map((entry) => [entry.id, entry])).values(),
  );
  return { ...query, entries };
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

  function invalidateDiagnostics(agentId: string) {
    void queryClient.invalidateQueries({
      queryKey: communicationDiagnosticsKey.all,
    });
    // Covers both journal list pages (by kind/filters) and delivery lifecycle
    // drill-down detail queries, which don't nest under a shared list prefix.
    void queryClient.invalidateQueries({ queryKey: communicationJournalKey.all });
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
    onSuccess: (data) => invalidateDiagnostics(data.connection.agentId),
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
    onSuccess: (_data, variables) => invalidateDiagnostics(variables.agentId),
  });

  return { createConnection, updateConnection, retireConnection, reconnectConnection, retryDelivery };
}
