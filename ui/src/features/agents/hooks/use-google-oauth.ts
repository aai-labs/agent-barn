"use client";

import { useCallback, useState } from "react";
import { z } from "zod";

import { api } from "@/shared/api";

const AuthorizeUrlSchema = z.object({ authorizeUrl: z.string().url() });

// Must match the message contract the backend callback posts (google_oauth/routes.py).
const MESSAGE_TYPE = "google-oauth";
const POPUP_FEATURES =
  "width=520,height=640,menubar=no,toolbar=no,location=no,status=no";

type OAuthMessage = {
  type?: string;
  refreshToken?: string;
  error?: string;
};

/**
 * Runs the Google OAuth popup flow and resolves with the captured Gmail refresh token.
 *
 * The popup is opened synchronously on click (before any await) so browsers don't block
 * it; we then fetch the authorize URL (authenticated) and point the popup at Google.
 * Google redirects the popup to our backend callback — served on this same origin via the
 * Next.js /api proxy — which postMessages the refresh token back here and closes.
 */
export function useGoogleOAuth() {
  const [isConnecting, setIsConnecting] = useState(false);

  const connectGoogle = useCallback(async (): Promise<string> => {
    setIsConnecting(true);
    const popup = window.open("about:blank", "google-oauth", POPUP_FEATURES);
    if (!popup) {
      setIsConnecting(false);
      throw new Error("Popup blocked. Allow popups for this site and try again.");
    }

    try {
      const { data } = await api.get<{ authorizeUrl: string }>(
        "/api/v1/integrations/google/authorize-url",
        { schema: AuthorizeUrlSchema },
      );
      popup.location.href = data.authorizeUrl;
    } catch (err) {
      popup.close();
      setIsConnecting(false);
      throw err;
    }

    return new Promise<string>((resolve, reject) => {
      let settled = false;

      const cleanup = () => {
        window.removeEventListener("message", onMessage);
        window.clearInterval(poll);
        setIsConnecting(false);
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
        // before this one settles) can't resolve this promise with its token/error.
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
        } else if (data.refreshToken) {
          const token = data.refreshToken;
          finish(() => resolve(token));
        } else {
          finish(() => reject(new Error("Google did not return a refresh token.")));
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
  }, []);

  return { connectGoogle, isConnecting };
}
