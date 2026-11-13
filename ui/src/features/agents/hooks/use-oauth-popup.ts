"use client";

const POPUP_FEATURES =
  "width=520,height=640,menubar=no,toolbar=no,location=no,status=no";

export type OAuthPopupMessage = {
  // Empty for an administrator approval, which returns no code.
  code: string;
  // Present when the backend signs a state it needs back to complete the sign-in.
  state?: string;
  adminConsent?: boolean;
};

type RawOAuthMessage = {
  type?: string;
  code?: string;
  state?: string;
  error?: string;
  adminConsent?: boolean;
};

export class OAuthPopupCancelledError extends Error {}

/**
 * For providers whose pages can sever the popup link. The result then arrives over a
 * same-origin BroadcastChannel, and a popup that reads as closed may still be open.
 */
export type OAuthPopupRelay = {
  channelName: string;
  state: string;
  timeoutMs: number;
  timeoutMessage: string;
  signal: AbortSignal;
  onPopupUnreachable: () => void;
};

/**
 * Opens the sign-in popup. Must be called synchronously from the click handler, before
 * any await, or browsers block it.
 */
export function openOAuthPopup(windowName: string): Window {
  const popup = window.open("about:blank", windowName, POPUP_FEATURES);
  if (!popup) {
    throw new Error("Popup blocked. Allow popups for this site and try again.");
  }
  return popup;
}

/**
 * Waits for the backend callback page in `popup` to post the sign-in result back.
 *
 * Shared by every provider on purpose: the origin check, pinning to this popup and the
 * settled guard are the delicate parts, and a second copy would drift the first time
 * either was fixed.
 */
export function waitForOAuthPopupMessage(
  popup: Window,
  messageType: string,
  providerName: string,
  // Shown when the popup is closed without a result. Some providers stop on their own
  // pages (e.g. an approval prompt), so this is the only place to explain what to do next.
  closedMessage = "Authentication was cancelled.",
  relay?: OAuthPopupRelay,
): Promise<OAuthPopupMessage> {
  return new Promise<OAuthPopupMessage>((resolve, reject) => {
    let settled = false;
    const activeRelay = typeof BroadcastChannel === "undefined" ? undefined : relay;
    const channel = activeRelay ? new BroadcastChannel(activeRelay.channelName) : null;

    const cleanup = () => {
      window.removeEventListener("message", onMessage);
      window.clearInterval(poll);
      window.clearTimeout(timeout);
      channel?.close();
      activeRelay?.signal.removeEventListener("abort", onAbort);
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
      const data = event.data as RawOAuthMessage;
      if (!data || data.type !== messageType) return;
      settle(data);
    }

    function onChannelMessage(event: MessageEvent) {
      const data = event.data as RawOAuthMessage;
      if (!data || data.type !== messageType || data.state !== activeRelay?.state) return;
      settle(data);
    }

    function onAbort() {
      try {
        popup.close();
      } catch {
        /* ignore */
      }
      finish(() => reject(new OAuthPopupCancelledError(closedMessage)));
    }

    function settle(data: RawOAuthMessage) {
      try {
        popup.close();
      } catch {
        /* ignore */
      }
      if (data.error) {
        const message = data.error;
        finish(() => reject(new Error(message)));
      } else if (data.code) {
        const result: OAuthPopupMessage = { code: data.code, ...(data.state ? { state: data.state } : {}) };
        finish(() => resolve(result));
      } else if (data.adminConsent) {
        finish(() => resolve({ code: "", adminConsent: true }));
      } else {
        finish(() => reject(new Error(`${providerName} did not return an authorization code.`)));
      }
    }

    window.addEventListener("message", onMessage);
    if (channel) channel.onmessage = onChannelMessage;
    activeRelay?.signal.addEventListener("abort", onAbort);
    const timeout = activeRelay
      ? window.setTimeout(() => finish(() => reject(new Error(activeRelay.timeoutMessage))), activeRelay.timeoutMs)
      : undefined;
    // If the user closes the popup without finishing, stop waiting.
    const poll = window.setInterval(() => {
      if (!popup.closed) return;
      if (activeRelay) {
        window.clearInterval(poll);
        activeRelay.onPopupUnreachable();
      } else {
        finish(() => reject(new Error(closedMessage)));
      }
    }, 500);
  });
}
