"use client";

import { useCallback, useState } from "react";
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { api } from "@/shared/api";
import { openOAuthPopup, waitForOAuthPopupMessage } from "@/features/agents/hooks/use-oauth-popup";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";

import { SyncLocationSchema, SyncProviderSchema, type SyncLocation, type SyncProvider } from "../schemas";
import { syncProviderKey } from "../utils";

// Mirrors MESSAGE_TYPE in api/domains/sync_provider/service.py.
const MESSAGE_TYPE = "sync-provider-oauth";
const POPUP_NAME = "sync-provider-sign-in";
const CLOSED_MESSAGE = "The sign-in window was closed before it finished.";

const AuthorizeUrlSchema = z.object({ authorizeUrl: z.string() });

type Purpose = "connect" | "disconnect";

function useProviderPath(providerKey: string) {
  const orgApiBase = useOrganizationApiBase();
  const { selectedOrganization } = useOrganizationContext();
  return {
    path: `${orgApiBase}/sync-providers/${providerKey}/connection`,
    organizationId: selectedOrganization?.id ?? "",
  };
}

/**
 * Puts the provider's new entry in the list straight away, then refetches the list: connecting or
 * disconnecting one provider changes whether the others may connect.
 */
function storeProvider(queryClient: QueryClient, organizationId: string, provider: SyncProvider) {
  const key = syncProviderKey.detail(organizationId);
  queryClient.setQueryData<SyncProvider[]>(key, (current) =>
    current?.map((item) => (item.key === provider.key ? provider : item)),
  );
  void queryClient.invalidateQueries({ queryKey: key });
}

/**
 * Signs in at the provider in a popup, then posts the code to `endpoint`. The popup opens
 * synchronously, before any await, or browsers block it.
 */
function useProviderSignIn(provider: SyncProvider, purpose: Purpose, endpoint: "sign-in" | "disconnect") {
  const { path, organizationId } = useProviderPath(provider.key);
  const queryClient = useQueryClient();
  const [isRunning, setIsRunning] = useState(false);

  const run = useCallback(async () => {
    const popup = openOAuthPopup(POPUP_NAME);
    setIsRunning(true);
    try {
      try {
        // Query params are sent as-is (not decamelized).
        const { data } = await api.get<{ authorizeUrl: string }>(`${path}/authorize-url`, {
          schema: AuthorizeUrlSchema,
          params: { purpose },
        });
        popup.location.href = data.authorizeUrl;
      } catch (err) {
        popup.close();
        throw err;
      }
      const { code, state } = await waitForOAuthPopupMessage(
        popup,
        MESSAGE_TYPE,
        provider.displayName,
        CLOSED_MESSAGE,
      );
      const { data } = await api.post<SyncProvider>(`${path}/${endpoint}`, { code, state }, { schema: SyncProviderSchema });
      storeProvider(queryClient, organizationId, data);
    } finally {
      setIsRunning(false);
    }
  }, [path, organizationId, queryClient, provider.displayName, purpose, endpoint]);

  return { run, isRunning };
}

export function useConnectSyncProvider(provider: SyncProvider) {
  const { run, isRunning } = useProviderSignIn(provider, "connect", "sign-in");
  return { connect: run, isConnecting: isRunning };
}

/** The person signs in again, because only their fresh sign-in may take back Agent Barn's access. */
export function useDisconnectSyncProvider(provider: SyncProvider) {
  const { run, isRunning } = useProviderSignIn(provider, "disconnect", "disconnect");
  return { disconnect: run, isDisconnecting: isRunning };
}

/** Forgets an unfinished connection so connecting can start again. */
export function useAbandonSyncProvider(provider: SyncProvider) {
  const { path, organizationId } = useProviderPath(provider.key);
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: async () => {
      await api.delete(path);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: syncProviderKey.detail(organizationId) });
      queryClient.removeQueries({ queryKey: syncProviderKey.lists() });
    },
  });

  return { abandon: mutation.mutateAsync, isAbandoning: mutation.isPending };
}

/** Locations matching `search`, seen by the person who signed in. Idle without a term. */
export function useSyncLocations(provider: SyncProvider, search: string) {
  const { path, organizationId } = useProviderPath(provider.key);
  const term = search.trim();

  const query = useQuery({
    queryKey: syncProviderKey.list({ scope: { organizationId, provider: provider.key }, filters: { search: term } }),
    queryFn: async () => {
      const response = await api.get<SyncLocation[]>(`${path}/locations`, {
        schema: z.array(SyncLocationSchema),
        params: { search: term },
      });
      return response.data;
    },
    enabled: Boolean(organizationId && term),
    retry: false,
  });

  return { locations: query.data, isSearching: query.isFetching, error: query.error };
}

/** Gives Agent Barn the chosen location and makes its folder there, which completes the connection. */
export function useChooseSyncLocation(provider: SyncProvider) {
  const { path, organizationId } = useProviderPath(provider.key);
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: async (locationId: string) => {
      const response = await api.post<SyncProvider>(`${path}/location`, { locationId }, { schema: SyncProviderSchema });
      return response.data;
    },
    onSuccess: (data) => {
      storeProvider(queryClient, organizationId, data);
      queryClient.removeQueries({ queryKey: syncProviderKey.lists() });
    },
  });

  return { chooseLocation: mutation.mutateAsync, isChoosing: mutation.isPending };
}
