"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useRef, useState } from "react";

import {
  OAuthPopupCancelledError,
  openOAuthPopup,
  waitForOAuthPopupMessage,
} from "@/features/agents/hooks/use-oauth-popup";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { api } from "@/shared/api";

import { McpSignInResultSchema, McpSignInStartSchema } from "../schemas";
import { mcpServersKey } from "../utils";

// Must match the message the backend callback posts (api/domains/mcp_servers/sign_in.py).
const MESSAGE_TYPE = "agentbarn-mcp-sign-in";
const CLOSED_MESSAGE = "The sign-in did not finish in time. Start it again.";
// Matches the signed state's lifetime on the API (STATE_TTL_SECONDS in sign_in.py).
const SIGN_IN_TIMEOUT_MS = 10 * 60 * 1000;

/**
 * Signs an OAuth MCP server in, for the organization or, with `agentId`, for one Agent.
 *
 * The popup opens before any request so browsers don't block it. The API redeems the code
 * and keeps the grant itself; nothing but the code and the signed state reaches the browser.
 */
export function useMcpServerSignIn() {
  const base = useOrganizationApiBase();
  const queryClient = useQueryClient();
  const [signingIn, setSigningIn] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);

  const signIn = useCallback(
    async ({ serverId, agentId }: { serverId: string; agentId?: string }) => {
      const popup = openOAuthPopup("mcp-server-sign-in");
      const controller = new AbortController();
      abort.current = controller;
      setSigningIn(serverId);
      try {
        let expectedState: string | undefined;
        try {
          const startUrl = agentId
            ? `${base}/agents/${agentId}/mcp-servers/${serverId}/sign-in`
            : `${base}/mcp-servers/${serverId}/sign-in`;
          const { data } = await api.post<{ authorizeUrl: string }>(startUrl, {}, { schema: McpSignInStartSchema });
          const authorizeUrl = new URL(data.authorizeUrl);
          // Checked here as well as in the schema: anything but an HTTPS page would run in
          // this popup, which still shares the app's origin.
          if (authorizeUrl.protocol !== "https:") throw new Error("The sign-in page must be an HTTPS URL.");
          expectedState = authorizeUrl.searchParams.get("state") ?? undefined;
          popup.location.href = authorizeUrl.toString();
        } catch (err) {
          popup.close();
          throw err;
        }
        // Some authorization servers sever the popup from this window, so the callback also
        // posts on a BroadcastChannel (the shared relay) and a closed-looking popup is not
        // taken as cancelled.
        const { code, state } = await waitForOAuthPopupMessage(
          popup,
          MESSAGE_TYPE,
          "The MCP server",
          CLOSED_MESSAGE,
          expectedState
            ? {
                channelName: MESSAGE_TYPE,
                state: expectedState,
                timeoutMs: SIGN_IN_TIMEOUT_MS,
                timeoutMessage: CLOSED_MESSAGE,
                signal: controller.signal,
                onPopupUnreachable: () => {},
              }
            : undefined,
        );
        const { data: result } = await api.post<{ toolCollisions: string[] }>(
          `${base}/mcp-servers/sign-in/complete`,
          { code, state },
          { schema: McpSignInResultSchema },
        );
        await queryClient.invalidateQueries({ queryKey: mcpServersKey.all });
        if (result.toolCollisions.length > 0) {
          // Saved, but held back: say why where the person is looking.
          throw new Error(
            `Signed in, but several tools would share these names in OpenClaw: ${result.toolCollisions.join(", ")}. ` +
              "Hide all but one of each in the server's tool filter; Agents can't use it until then.",
          );
        }
      } catch (err) {
        if (err instanceof OAuthPopupCancelledError) return;
        throw err;
      } finally {
        if (abort.current === controller) abort.current = null;
        setSigningIn(null);
      }
    },
    [base, queryClient],
  );

  const cancelSignIn = useCallback(() => abort.current?.abort(), []);

  return { signIn, signingIn, cancelSignIn };
}

/** Forgets the organization's sign-in of an OAuth server. */
export function useMcpServerSignOut() {
  const base = useOrganizationApiBase();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (serverId: string) => {
      await api.delete(`${base}/mcp-servers/${serverId}/sign-in`);
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: mcpServersKey.all }),
  });
}
