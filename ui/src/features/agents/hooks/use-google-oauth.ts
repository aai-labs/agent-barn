"use client";

import { useCallback, useState } from "react";
import { z } from "zod";

import { api } from "@/shared/api";

const AuthorizeUrlSchema = z.object({ authorizeUrl: z.string().url() });
const TokenSchema = z.object({ refreshToken: z.string().min(1) });

// Must match the message contract the backend callback posts (google_oauth/routes.py).
const MESSAGE_TYPE = "google-oauth";
const POPUP_FEATURES =
  "width=520,height=640,menubar=no,toolbar=no,location=no,status=no";

type OAuthMessage = {
  type?: string;
  code?: string;
  error?: string;
};

// Optional user-supplied Google client. When omitted, the app-owned client configured
// on the backend is used.
export type GoogleClientCredentials = {
  clientId: string;
  clientSecret: string;
};

// What the flow yields: the captured refresh token plus the client it was issued under.
// clientId/clientSecret are empty strings for the app-owned client (so agent-start
// backfills them from config); populated when the user brought their own client.
export type GoogleOAuthResult = {
  refreshToken: string;
  clientId: string;
  clientSecret: string;
};

/**
 * Runs the Google OAuth popup flow and resolves with the captured refresh token for the
 * requested Google provider.
 *
 * The popup is opened synchronously on click (before any await) so browsers don't block
 * it; we then fetch the authorize URL (authenticated) and point the popup at Google.
 * Google redirects the popup to our backend callback — served on this same origin via the
 * Next.js /api proxy — which postMessages the raw authorization code back here and closes.
 * We then exchange that code for a refresh token via /token (the client secret, if any,
 * travels only in that authenticated request body — never through Google or a URL).
 */
export function useGoogleOAuth() {
  const [isConnecting, setIsConnecting] = useState(false);

  const connectGoogle = useCallback(
    async (
      creds?: GoogleClientCredentials,
      // Which Google integration is being connected — decides the scopes the backend
      // requests. Defaults to gmail, the only provider this flow originally served.
      provider: string = "gmail",
    ): Promise<GoogleOAuthResult> => {
      setIsConnecting(true);
      const popup = window.open("about:blank", "google-oauth", POPUP_FEATURES);
      if (!popup) {
        setIsConnecting(false);
        throw new Error("Popup blocked. Allow popups for this site and try again.");
      }

      try {
        const { data } = await api.get<{ authorizeUrl: string }>(
          "/api/v1/integrations/google/authorize-url",
          {
            schema: AuthorizeUrlSchema,
            // Query params are sent as-is (not decamelized), so use the snake_case key.
            params: creds?.clientId ? { provider, client_id: creds.clientId } : { provider },
          },
        );
        popup.location.href = data.authorizeUrl;
      } catch (err) {
        popup.close();
        setIsConnecting(false);
        throw err;
      }

      try {
        // Wait for the callback popup to postMessage the authorization code back.
        const code = await new Promise<string>((resolve, reject) => {
          let settled = false;

          const cleanup = () => {
            window.removeEventListener("message", onMessage);
            window.clearInterval(poll);
          };
          const finish = (fn: () => void) => {
            if (settled) return;
            settled = true;
            cleanup();
            fn();
          };

          function onMessage(event: MessageEvent) {
            // The callback is same-origin (served through the /api proxy); reject anything else.
            if (event.origin !== window.location.origin) return;
            // Pin to this call's own popup so a concurrent flow (e.g. a second popup opened
            // before this one settles) can't resolve this promise with its code/error.
            if (event.source !== popup) return;
            const data = event.data as OAuthMessage;
            if (!data || data.type !== MESSAGE_TYPE) return;
            try {
              popup?.close();
            } catch {
              /* ignore */
            }
            if (data.error) {
              finish(() => reject(new Error(data.error)));
            } else if (data.code) {
              const authCode = data.code;
              finish(() => resolve(authCode));
            } else {
              finish(() =>
                reject(new Error("Google did not return an authorization code.")),
              );
            }
          }

          window.addEventListener("message", onMessage);
          // If the user closes the popup without finishing, stop waiting.
          const poll = window.setInterval(() => {
            if (popup?.closed) {
              finish(() => reject(new Error("Authentication was cancelled.")));
            }
          }, 500);
        });

        // Exchange the code for a refresh token server-side. The client secret (if the
        // user supplied their own client) rides only in this authenticated request body.
        const { data } = await api.post<{ refreshToken: string }>(
          "/api/v1/integrations/google/token",
          creds
            ? { code, clientId: creds.clientId, clientSecret: creds.clientSecret }
            : { code },
          { schema: TokenSchema },
        );

        return {
          refreshToken: data.refreshToken,
          clientId: creds?.clientId ?? "",
          clientSecret: creds?.clientSecret ?? "",
        };
      } finally {
        setIsConnecting(false);
      }
    },
    [],
  );

  return { connectGoogle, isConnecting };
}
