/** WhatsApp runs only in a Hermes Agent's own runtime so far; the API refuses the rest. */
export function offersWhatsApp(agent: { agentType: string; parentAgentId: string | null }): boolean {
  return agent.agentType === "hermes" && !agent.parentAgentId;
}

export type WhatsAppPairingEvent =
  | { event: "qr"; qr: string }
  | { event: "connected"; phone: string | null }
  | { event: "linked" }
  | { event: "expired" }
  | { event: "error"; message: string };

export function parsePairingEvent(data: string): WhatsAppPairingEvent | null {
  try {
    const parsed: unknown = JSON.parse(data);
    if (parsed && typeof parsed === "object" && "event" in parsed) return parsed as WhatsAppPairingEvent;
  } catch {
    // Not an event line.
  }
  return null;
}
