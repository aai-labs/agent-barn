"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/shared/api";

export type SseStreamStatus = "idle" | "connecting" | "streaming" | "disconnected";

interface UseSseStreamOptions {
  /** Full stream URL, or null while a required id/param isn't ready yet. */
  url: string | null;
  enabled: boolean;
  onLine: (line: string) => void;
}

const RECONNECT_BASE_MS = 1_000;
const RECONNECT_MAX_MS = 15_000;

/**
 * Bearer-authenticated SSE client shared by every dashboard stream
 * (Agent logs, Web Chat): connects, reads `data: ` lines out of the
 * `\n\n`-delimited frame buffer, and reconnects with exponential backoff.
 */
export function useSseStream({ url, enabled, onLine }: UseSseStreamOptions) {
  const [status, setStatus] = useState<SseStreamStatus>("idle");
  const abortRef = useRef<AbortController | null>(null);
  const onLineRef = useRef(onLine);
  onLineRef.current = onLine;
  const retriesRef = useRef(0);
  const mountedRef = useRef(true);
  const [prevActive, setPrevActive] = useState(enabled && !!url);

  const active = enabled && !!url;
  if (active !== prevActive) {
    setPrevActive(active);
    if (!active) {
      setStatus("idle");
    }
  }

  const disconnect = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
  }, []);

  useEffect(() => {
    mountedRef.current = true;

    if (!enabled || !url) {
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

      try {
        const authHeaders = await api.getAuthHeaders();
        if (!authHeaders.Authorization) {
          setStatus("disconnected");
          return;
        }
        if (!mountedRef.current || controller.signal.aborted) return;

        const response = await fetch(url as string, {
          headers: {
            ...authHeaders,
            Accept: "text/event-stream",
          },
          signal: controller.signal,
        });

        if (!response.ok || !response.body) {
          if (response.status === 401) {
            await api.getAuthHeaders(true);
          }
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
  }, [url, enabled, disconnect]);

  return { status, disconnect };
}
