"use client";

import { useCallback, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { api } from "@/shared/api";
import { openOAuthPopup, waitForOAuthPopupMessage } from "@/features/agents/hooks/use-oauth-popup";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";

import {
  OneDriveSyncConnectionSchema,
  OneDriveSyncSiteSchema,
  type OneDriveSyncConnection,
  type OneDriveSyncSite,
} from "../schemas";
import { oneDriveSyncKey } from "../utils";

// Mirrors MESSAGE_TYPE in api/domains/onedrive_sync/service.py.
const MESSAGE_TYPE = "onedrive-sync-oauth";
const POPUP_NAME = "onedrive-sync-sign-in";
const CLOSED_MESSAGE = "The Microsoft window was closed before connecting finished.";

const AuthorizeUrlSchema = z.object({ authorizeUrl: z.string() });

function useConnectionPath() {
  const orgApiBase = useOrganizationApiBase();
  const { selectedOrganization } = useOrganizationContext();
  return { path: `${orgApiBase}/onedrive-sync/connection`, organizationId: selectedOrganization?.id ?? "" };
}

/**
 * Connects OneDrive: Microsoft admin consent, then sign-in, in one popup the server keeps
 * moving. The API redeems the code into a pending connection, which the site picker finishes.
 */
export function useConnectOneDrive() {
  const { path, organizationId } = useConnectionPath();
  const queryClient = useQueryClient();
  const [isConnecting, setIsConnecting] = useState(false);

  const connect = useCallback(async () => {
    const popup = openOAuthPopup(POPUP_NAME);
    setIsConnecting(true);
    try {
      try {
        // Query params are sent as-is (not decamelized).
        const { data } = await api.get<{ authorizeUrl: string }>(`${path}/authorize-url`, {
          schema: AuthorizeUrlSchema,
          params: { purpose: "connect" },
        });
        popup.location.href = data.authorizeUrl;
      } catch (err) {
        popup.close();
        throw err;
      }
      const { code, state } = await waitForOAuthPopupMessage(popup, MESSAGE_TYPE, "Microsoft", CLOSED_MESSAGE);
      const { data } = await api.post<OneDriveSyncConnection>(
        `${path}/sign-in`,
        { code, state },
        { schema: OneDriveSyncConnectionSchema },
      );
      queryClient.setQueryData(oneDriveSyncKey.detail(organizationId), data);
    } finally {
      setIsConnecting(false);
    }
  }, [path, organizationId, queryClient]);

  return { connect, isConnecting };
}

/** SharePoint sites matching `search`, seen by the administrator who signed in. Idle without a term. */
export function useOneDriveSyncSites(search: string) {
  const { path, organizationId } = useConnectionPath();
  const term = search.trim();

  const query = useQuery({
    queryKey: oneDriveSyncKey.list({ scope: { organizationId }, filters: { search: term } }),
    queryFn: async () => {
      const response = await api.get<OneDriveSyncSite[]>(`${path}/sites`, {
        schema: z.array(OneDriveSyncSiteSchema),
        params: { search: term },
      });
      return response.data;
    },
    enabled: Boolean(organizationId && term),
    retry: false,
  });

  return { sites: query.data, isSearching: query.isFetching, error: query.error };
}

/** Grants Agent Barn the chosen site and creates its folder there, which completes the connection. */
export function useChooseOneDriveSite() {
  const { path, organizationId } = useConnectionPath();
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: async (siteId: string) => {
      const response = await api.post<OneDriveSyncConnection>(
        `${path}/site`,
        { siteId },
        { schema: OneDriveSyncConnectionSchema },
      );
      return response.data;
    },
    onSuccess: (data) => {
      queryClient.setQueryData(oneDriveSyncKey.detail(organizationId), data);
      void queryClient.invalidateQueries({ queryKey: oneDriveSyncKey.lists() });
    },
  });

  return { chooseSite: mutation.mutateAsync, isChoosing: mutation.isPending };
}
