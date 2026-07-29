"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useAuthStore } from "@/auth/providers/auth-store";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

export type StreamStatus = "idle" | "connecting" | "streaming" | "disconnected";

interface UseAgentLogStreamOptions {
  agentId: string;
  enabled: boolean;
  onLine: (line: string) => void;
}

const RECONNECT_BASE_MS = 1_000;
const RECONNECT_MAX_MS = 15_000;

export function useAgentLogStream({
  agentId,
  enabled,
  onLine,
}: UseAgentLogStreamOptions) {
  const orgApiBase = useOrganizationApiBase();
  const [status, setStatus] = useState<StreamStatus>("idle");
  const abortRef = useRef<AbortController | null>(null);
  const onLineRef = useRef(onLine);
  onLineRef.current = onLine;
  const retriesRef = useRef(0);
  const mountedRef = useRef(true);
  const [prevEnabled, setPrevEnabled] = useState(enabled);

  if (enabled !== prevEnabled) {
    setPrevEnabled(enabled);
    if (!enabled) {
      setStatus("idle");
    }
  }

  const disconnect = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
  }, []);

  useEffect(() => {
    mountedRef.current = true;

    if (!enabled) {
      disconnect();
      retriesRef.current = 0;
      return;
    }

    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    async function connect() {
      if (!mountedRef.current) return;

      const controller = new AbortController();
      abortRef.current = controller;
      setStatus("connecting");

      const tokens = useAuthStore.getState().authToken;
      if (!tokens?.accessToken) {
        setStatus("disconnected");
        return;
      }

      try {
        const response = await fetch(
          `${orgApiBase}/agents/${agentId}/logs/stream?tail_lines=0`,
          {
            headers: {
              Authorization: `Bearer ${tokens.accessToken}`,
              Accept: "text/event-stream",
            },
            signal: controller.signal,
          },
        );

        if (!response.ok || !response.body) {
          setStatus("disconnected");
          scheduleReconnect();
          return;
        }

        setStatus("streaming");
        retriesRef.current = 0;

        const reader = response.body
          .pipeThrough(new TextDecoderStream())
          .getReader();

        let buffer = "";
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += value;
          const parts = buffer.split("\n\n");
          buffer = parts.pop() ?? "";
          for (const part of parts) {
            for (const line of part.split("\n")) {
              if (line.startsWith("data: ")) {
                onLineRef.current(line.slice(6));
              }
            }
          }
        }

        if (mountedRef.current) {
          setStatus("disconnected");
          scheduleReconnect();
        }
      } catch (err) {
        if ((err as DOMException).name === "AbortError") return;
        if (mountedRef.current) {
          setStatus("disconnected");
          scheduleReconnect();
        }
      }
    }

    function scheduleReconnect() {
      if (!mountedRef.current) return;
      const delay = Math.min(
        RECONNECT_BASE_MS * 2 ** retriesRef.current,
        RECONNECT_MAX_MS,
      );
      retriesRef.current += 1;
      reconnectTimer = setTimeout(() => {
        void connect();
      }, delay);
    }

    void connect();

    return () => {
      mountedRef.current = false;
      disconnect();
      if (reconnectTimer) clearTimeout(reconnectTimer);
    };
  }, [agentId, enabled, disconnect, orgApiBase]);

  return { status, disconnect };
}
