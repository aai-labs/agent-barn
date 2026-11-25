"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { api } from "@/shared/api";

import { parsePairingEvent } from "../whatsapp";

export type WhatsAppPairingState =
  | { phase: "idle" }
  | { phase: "starting" }
  /** The QR code as its text payload (Hermes) or as a rendered PNG data URL (OpenClaw). */
  | { phase: "scan"; qr: { text: string } | { image: string } }
  | { phase: "connecting"; phone: string | null }
  | { phase: "linked"; phone: string | null }
  | { phase: "expired" }
  | { phase: "failed"; message: string };

async function errorDetail(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "detail" in body && typeof body.detail === "string") return body.detail;
  } catch {
    // Fall through to the generic message.
  }
  return "Could not start linking. Try again.";
}

/**
 * One pairing attempt at a time, streamed from the Agent's pod. It is never retried
 * on its own: a new attempt replaces the QR code the person may be scanning.
 */
export function useWhatsAppPairing(agentId: string, connectionId: string) {
  const orgApiBase = useOrganizationApiBase();
  const [state, setState] = useState<WhatsAppPairingState>({ phase: "idle" });
  const abortRef = useRef<AbortController | null>(null);

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setState({ phase: "idle" });
  }, []);

  useEffect(() => () => abortRef.current?.abort(), []);

  const start = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setState({ phase: "starting" });
    let phone: string | null = null;
    let finished = false;
    try {
      const response = await fetch(`${orgApiBase}/agents/${agentId}/connections/${connectionId}/whatsapp-pairing`, {
        method: "POST",
        headers: { ...(await api.getAuthHeaders()), Accept: "text/event-stream" },
        signal: controller.signal,
      });
      if (!response.ok || !response.body) {
        setState({ phase: "failed", message: await errorDetail(response) });
        return;
      }
      const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
      let buffer = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += value;
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";
        for (const frame of frames) {
          if (!frame.startsWith("data: ")) continue;
          const event = parsePairingEvent(frame.slice(6));
          if (event?.event === "qr") setState({ phase: "scan", qr: { text: event.qr } });
          else if (event?.event === "qr_image") setState({ phase: "scan", qr: { image: event.image } });
          else if (event?.event === "connected") {
            phone = event.phone;
            setState({ phase: "connecting", phone });
          } else if (event?.event === "linked") {
            finished = true;
            setState({ phase: "linked", phone });
          } else if (event?.event === "expired") {
            finished = true;
            setState({ phase: "expired" });
          } else if (event?.event === "error") {
            finished = true;
            setState({ phase: "failed", message: event.message });
          }
        }
      }
      if (!finished) setState({ phase: "failed", message: "Linking stopped before the phone was linked. Try again." });
    } catch (cause) {
      if ((cause as DOMException).name === "AbortError") return;
      setState({ phase: "failed", message: "Lost the connection to the Agent while linking. Try again." });
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
    }
  }, [orgApiBase, agentId, connectionId]);

  return { state, start, cancel };
}
