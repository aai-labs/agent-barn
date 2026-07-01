"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useAuthStore } from "@/auth/providers/auth-store";

interface UseAgentLogStreamOptions {
  agentId: string;
  enabled: boolean;
  onLine: (line: string) => void;
}

export function useAgentLogStream({
  agentId,
  enabled,
  onLine,
}: UseAgentLogStreamOptions) {
  const [isConnected, setIsConnected] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const onLineRef = useRef(onLine);
  onLineRef.current = onLine;

  const disconnect = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
  }, []);

  useEffect(() => {
    if (!enabled) {
      disconnect();
      setIsConnected(false);
      return;
    }

    const controller = new AbortController();
    abortRef.current = controller;

    async function run() {
      const tokens = useAuthStore.getState().authToken;
      if (!tokens?.accessToken) return;

      try {
        const response = await fetch(
          `/api/v1/agents/${agentId}/logs/stream?tail_lines=0`,
          {
            headers: {
              Authorization: `Bearer ${tokens.accessToken}`,
              Accept: "text/event-stream",
            },
            signal: controller.signal,
          },
        );

        if (!response.ok || !response.body) return;
        setIsConnected(true);

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
      } catch (err) {
        if ((err as DOMException).name === "AbortError") return;
      } finally {
        setIsConnected(false);
      }
    }

    void run();
    return () => disconnect();
  }, [agentId, enabled, disconnect]);

  return { isConnected, disconnect };
}
