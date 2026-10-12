"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";
import { api } from "@/shared/api";
import { createQueryKeyStructure } from "@/shared/query-keys";

import {
  TelegramLinkedAccountSchema,
  TelegramLinkTokenSchema,
  type TelegramLinkedAccount,
  type TelegramLinkToken,
} from "../schemas";

export const telegramLinkedAccountsKey = createQueryKeyStructure("telegram-linked-accounts");
export const telegramLinkTokenKey = createQueryKeyStructure("telegram-link-token");

// How often to check whether someone pressed Start while a link is open.
const LINK_STATUS_INTERVAL_MS = 2000;

function connectionPath(orgApiBase: string, agentId: string, connectionId: string) {
  return `${orgApiBase}/agents/${agentId}/connections/${connectionId}`;
}

export function useTelegramLinkedAccounts(
  agentId: string,
  connectionId: string,
  { whileLinking = false }: { whileLinking?: boolean } = {},
) {
  const orgApiBase = useOrganizationApiBase();
  const { selectedOrganization } = useOrganizationContext();
  const organizationId = selectedOrganization?.id ?? "";
  const query = useQuery({
    queryKey: telegramLinkedAccountsKey.list({ organizationId, agentId, connectionId }),
    queryFn: async () => {
      const response = await api.get<TelegramLinkedAccount[]>(
        `${connectionPath(orgApiBase, agentId, connectionId)}/telegram-links`,
        { schema: z.array(TelegramLinkedAccountSchema) },
      );
      return response.data;
    },
    enabled: Boolean(organizationId && agentId && connectionId),
    // A pending link lands in this list the moment someone presses Start.
    refetchInterval: whileLinking ? LINK_STATUS_INTERVAL_MS : false,
  });
  return { linkedAccounts: query.data ?? [], isLoadingLinkedAccounts: query.isLoading, error: query.error };
}

export function useTelegramLinkStatus(agentId: string, connectionId: string, tokenId: string | null) {
  const orgApiBase = useOrganizationApiBase();
  const { selectedOrganization } = useOrganizationContext();
  const organizationId = selectedOrganization?.id ?? "";
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: telegramLinkTokenKey.detail(`${organizationId}:${connectionId}:${tokenId ?? ""}`),
    queryFn: async () => {
      const response = await api.get<TelegramLinkToken>(
        `${connectionPath(orgApiBase, agentId, connectionId)}/telegram-link-tokens/${tokenId}`,
        { schema: TelegramLinkTokenSchema },
      );
      if (response.data.status === "linked") {
        // Polling stops at "linked", so refresh the account list exactly once here.
        void queryClient.invalidateQueries({
          queryKey: telegramLinkedAccountsKey.list({ organizationId, agentId, connectionId }),
        });
      }
      return response.data;
    },
    enabled: Boolean(organizationId && agentId && connectionId && tokenId),
    refetchInterval: (current) =>
      current.state.data === undefined || current.state.data.status === "waiting" ? LINK_STATUS_INTERVAL_MS : false,
  });
  return { linkStatus: query.data };
}

export function useTelegramAccountLinkingActions(agentId: string, connectionId: string) {
  const orgApiBase = useOrganizationApiBase();
  const { selectedOrganization } = useOrganizationContext();
  const organizationId = selectedOrganization?.id ?? "";
  const queryClient = useQueryClient();

  const createLink = useMutation({
    mutationFn: async () => {
      const response = await api.post<TelegramLinkToken>(
        `${connectionPath(orgApiBase, agentId, connectionId)}/telegram-link-tokens`,
        undefined,
        { schema: TelegramLinkTokenSchema },
      );
      return response.data;
    },
  });

  const unlink = useMutation({
    mutationFn: async (linkId: string) => {
      await api.delete(`${connectionPath(orgApiBase, agentId, connectionId)}/telegram-links/${linkId}`);
    },
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: telegramLinkedAccountsKey.list({ organizationId, agentId, connectionId }),
      }),
  });

  return { createLink, unlink };
}
