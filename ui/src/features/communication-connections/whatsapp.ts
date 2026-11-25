/**
 * Why this Agent can't have WhatsApp, or null when it can. Hermes and OpenClaw Agents
 * both can; a Bot can't, because one linked phone serves the whole Agent pod.
 */
export function whatsAppUnavailableReason(agent: { parentAgentId: string | null }): string | null {
  return agent.parentAgentId ? "Bots share their Parent Agent's phone. Add WhatsApp to the Parent Agent." : null;
}

/** What happens to the linked phone when someone links again, per runtime. */
export function whatsAppRelinkNote(agentType: string): string {
  return agentType === "openclaw"
    ? "Linking again unlinks the current phone straight away, even if you cancel."
    : "The current phone stays linked until the new one is.";
}

export type WhatsAppPairingEvent =
  | { event: "qr"; qr: string }
  | { event: "qr_image"; image: string }
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

function list(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function count(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** Plain-language steps for talking to the Agent on WhatsApp, from the Connection's (camelCased) settings. */
export function whatsAppReach(settings: Record<string, unknown>): { title: string; lines: string[] } {
  if (settings.mode === "self_chat") {
    return {
      title: "How to talk to this Agent",
      lines: [
        "On the linked phone, open WhatsApp and start a chat with yourself: New chat → Message yourself, at the top of your contacts.",
        "Send a message there. The Agent answers in the same chat, and its replies start with 🤖.",
        "No one else can reach it, and your chats with other people are left alone.",
      ],
    };
  }
  const numbers = list(settings.allowedNumbers);
  const groups = list(settings.allowedGroupIds);
  const dmPolicy = settings.dmPolicy ?? "allowlist";
  const groupPolicy = settings.groupPolicy ?? "off";
  const mention = settings.requireMention === false ? "to every message" : "when @mentioned or replied to";

  const dms =
    dmPolicy === "open"
      ? "Anyone who has the linked number can message it directly."
      : dmPolicy === "allowlist" && numbers.length > 0
        ? `Direct messages from ${count(numbers.length, "allowed number", "allowed numbers")} are answered; others are ignored.`
        : dmPolicy === "allowlist"
          ? "No numbers are allowed yet, so direct messages are ignored. Add them under Allowed numbers."
          : "Direct messages are ignored.";
  const inGroups =
    groupPolicy === "open"
      ? `Add the linked number to a group; it answers there ${mention}.`
      : groupPolicy === "allowlist" && groups.length > 0
        ? `In ${count(groups.length, "allowed group", "allowed groups")}, it answers ${mention}.`
        : "Groups are ignored.";
  return {
    title: "How people reach this Agent",
    lines: [
      dms,
      inGroups,
      "It answers as the linked number. To try it, message it from another phone: direct messages typed on the linked phone itself are ignored.",
    ],
  };
}
