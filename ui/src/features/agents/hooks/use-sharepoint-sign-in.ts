"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import { z } from "zod";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { api } from "@/shared/api";

import { agentsKey } from "../utils";
import { openOAuthPopup, waitForOAuthPopupMessage } from "./use-oauth-popup";

const AuthorizeUrlSchema = z.object({ authorizeUrl: z.string().url() });
const SignInSchema = z.object({ email: z.string(), readOnly: z.boolean() });
const SetupSchema = z.object({
  appId: z.string(),
  tenantId: z.string(),
  redirectUri: z.string().url(),
  adminConsentUrl: z.string().url(),
  readOnlyAdminConsentUrl: z.string().url(),
});

// Must match the message contract the backend callback posts (sharepoint_service.py).
const MESSAGE_TYPE = "microsoft-oauth";

// Microsoft keeps "Need admin approval" and redirect URI errors on its own pages, so a
// popup closed without a result is the only signal we get for either.
const CLOSED_MESSAGE =
  "The sign-in window closed before it finished. If Microsoft asked for administrator approval, " +
  "have a Microsoft 365 administrator approve SharePoint access (step 5 above). If it reported a " +
  "problem with the redirect URI, check it is listed under Mobile and desktop applications and that " +
  "Allow public client flows is on (steps 2 and 3).";

const ADMIN_CLOSED_MESSAGE = "The approval window closed before Microsoft confirmed the approval.";

export type SharePointSignInResult = z.infer<typeof SignInSchema>;
export type SharePointSetup = z.infer<typeof SetupSchema>;

function sharepointBase(orgApiBase: string, agentId: string) {
  return `${orgApiBase}/agents/${agentId}/integrations/sharepoint`;
}

/** The agent's Teams app details the customer needs to set it up. Nothing secret. */
export function useSharePointSetup(agentId: string, connectionId: string | undefined) {
  const orgApiBase = useOrganizationApiBase();
  return useQuery({
    queryKey: [...agentsKey.detail(agentId), "sharepoint-setup", connectionId],
    queryFn: async () => {
      const { data } = await api.get<SharePointSetup>(`${sharepointBase(orgApiBase, agentId)}/setup`, {
        schema: SetupSchema,
        params: { connection_id: connectionId },
      });
      return data;
    },
    enabled: Boolean(connectionId),
  });
}

/**
 * Signs SharePoint in for an agent, with Microsoft, on the agent's Teams app.
 *
 * The API redeems the code and stores the credential itself, returning only who signed
 * in; the agent is refetched afterwards so the new credential shows up.
 */
export function useSharePointSignIn(agentId: string) {
  const orgApiBase = useOrganizationApiBase();
  const queryClient = useQueryClient();
  const [isSigningIn, setIsSigningIn] = useState(false);

  const signIn = useCallback(
    async ({ connectionId, readOnly }: { connectionId: string; readOnly: boolean }) => {
      const popup = openOAuthPopup("microsoft-sign-in");
      setIsSigningIn(true);
      const base = sharepointBase(orgApiBase, agentId);
      try {
        try {
          const { data } = await api.get<{ authorizeUrl: string }>(`${base}/authorize-url`, {
            schema: AuthorizeUrlSchema,
            // Query params are sent as-is (not decamelized), so use snake_case keys.
            params: { connection_id: connectionId, read_only: readOnly ? "true" : "false" },
          });
          popup.location.href = data.authorizeUrl;
        } catch (err) {
          popup.close();
          throw err;
        }

        const { code, state } = await waitForOAuthPopupMessage(popup, MESSAGE_TYPE, "Microsoft", CLOSED_MESSAGE);
        const { data } = await api.post<SharePointSignInResult>(
          `${base}/sign-in`,
          { code, state },
          { schema: SignInSchema },
        );
        void queryClient.invalidateQueries({ queryKey: agentsKey.detail(agentId) });
        return data;
      } finally {
        setIsSigningIn(false);
      }
    },
    [agentId, orgApiBase, queryClient],
  );

  return { signIn, isSigningIn };
}

/** Opens Microsoft's organization-wide approval page; resolves once Microsoft confirms it. */
export function useAdministratorApproval() {
  const [isApproving, setIsApproving] = useState(false);

  const approve = useCallback(async (adminConsentUrl: string) => {
    const popup = openOAuthPopup("microsoft-admin-approval");
    popup.location.href = adminConsentUrl;
    setIsApproving(true);
    try {
      await waitForOAuthPopupMessage(popup, MESSAGE_TYPE, "Microsoft", ADMIN_CLOSED_MESSAGE);
    } finally {
      setIsApproving(false);
    }
  }, []);

  return { approve, isApproving };
}
